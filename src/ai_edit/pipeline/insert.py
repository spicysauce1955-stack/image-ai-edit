"""Object-insertion orchestrator.

Glues the providers together into the insertion pipeline:

::

    scene + reference + instruction + (mode, polygon, system_prompt)
        │
        ├─► (optional) Replicate · Grounded-SAM
        │       → masks dumped for inspection only
        │
        ├─► Gemini · 2.5 Flash Image
        │       inputs: [scene, reference, aux?]
        │       output: raw composite
        │
        └─► (optional) fal.ai · IC-Light v2
                relit composite

Placement modes
---------------
The user picks one of three modes per request. The mode controls
*what* gets sent to Gemini as the (optional) third image and *how* the
prompt frames it:

- ``"free"`` — no polygon, no third image. Gemini chooses placement.
- ``"mask"`` — polygon → binary PNG (white = place here, black =
  preserve), sent as image 3 with mask-aware prompt language.
- ``"overlay"`` — polygon → a copy of the scene with the reference
  *pre-placed* inside the polygon shape (Pillow paste + polygon clip),
  sent as image 3 with "clean this up" prompt language.

Refinement mode (``previous_composite`` set) is orthogonal — it always
overrides the placement mode because refinement is about iterating on
a result rather than re-specifying the placement region.

System prompt
-------------
Each mode has a default system prompt template exposed as a constant
below and via :func:`default_system_prompt`. Callers can override the
template per request by passing ``system_prompt=...``; the user's
``instruction`` is concatenated with the chosen template to form the
full prompt sent to Gemini. The ``/api/defaults`` server endpoint
serves these defaults to the UI so the textarea can show them.

Gemini and "literal" masks
--------------------------
Gemini 2.5 Flash Image does not consume a literal alpha mask channel
— only multi-image conditioning + prompt text. So both mask and
overlay modes are *strong guidance*, not hard constraints. For a hard
alpha mask the next move is gpt-image-1 (see
``docs/contributing.md`` for the swap recipe); the existing
``mask_polygon`` carries straight over because rasterization happens
in this orchestration layer rather than in the provider.
"""

from __future__ import annotations

import io
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw

from ..models.base import SegmentationMask
from ..providers import FalAI, Gemini, Replicate

Mode = Literal["free", "mask", "overlay"]
AuxKind = Literal["mask", "overlay", "previous"]


# ---------------------------------------------------------------------------
# Default system prompts — the part appended after the user's instruction.
# ---------------------------------------------------------------------------

DEFAULT_FREE_PROMPT = (
    "Image 1 is the scene. Image 2 is the reference object to insert. "
    "Place the object photorealistically in the scene: respect the existing "
    "ground plane, perspective, and occlusion (objects in front of the "
    "inserted region must remain in front). Match the scene's lighting: "
    "infer the sun direction from the existing shadows in image 1, then "
    "shade the inserted object accordingly and cast a soft, realistic "
    "ground shadow underneath it that falls in the same direction as the "
    "other shadows in the scene. Preserve the object's exact shape, color, "
    "material, and texture from image 2 — do not restyle or regenerate "
    "the object. Output only the final composited image."
)

DEFAULT_MASK_PROMPT = (
    "Image 1 is the scene. Image 2 is the reference object to insert. "
    "Image 3 is a binary mask the user drew on the scene: WHITE pixels "
    "mark the exact region where the reference object should be placed; "
    "BLACK pixels must remain unchanged from image 1. Place the object "
    "photorealistically inside the white region, respecting perspective "
    "and the existing ground plane. Preserve the object's exact shape, "
    "color, material, and texture from image 2 — do not restyle or "
    "regenerate it. Match the scene's lighting: infer the sun direction "
    "from the existing shadows in image 1, then shade the inserted "
    "object accordingly and cast a soft, realistic ground shadow "
    "consistent with that direction. Foreground objects in image 1 "
    "that visually overlap the white region must remain in front of "
    "the inserted object. Output only the final composited image."
)

DEFAULT_OVERLAY_PROMPT = (
    "Image 1 is the original scene. Image 2 is the reference object. "
    "Image 3 is image 1 with the reference roughly pre-placed inside the "
    "region the user drew. Treat image 3 as a placement hint: keep the "
    "object exactly where it appears in image 3, but blend it into the "
    "scene photorealistically. Smooth the seams between the inserted "
    "object and the surrounding scene. Match the scene's lighting and "
    "shadow direction from image 1; cast a soft realistic ground shadow "
    "under the object. Preserve the object's exact shape, color, "
    "material, and texture from image 2 — do not restyle or regenerate "
    "it. Foreground objects in image 1 that overlap the placement "
    "region must remain in front of the inserted object. Output only "
    "the final composited image."
)

DEFAULT_REFINE_PROMPT = (
    "Image 1 is the original scene. Image 2 is the reference object. "
    "Image 3 is your previous attempt at the composite. Apply the user's "
    "refinement to image 3 — do not restart from scratch. Preserve "
    "everything that is already correct: object appearance from image 2, "
    "scene lighting and shadow direction from image 1, occlusion of "
    "foreground objects, and overall composition. Only change what the "
    "refinement explicitly asks for. Output only the updated composite."
)


def default_system_prompt(mode: Mode | Literal["refine"]) -> str:
    """Return the default system prompt for a given mode.

    Used both at request time (when the caller didn't pass an override)
    and by the ``/api/defaults`` endpoint that pre-fills the UI.
    """
    return {
        "free": DEFAULT_FREE_PROMPT,
        "mask": DEFAULT_MASK_PROMPT,
        "overlay": DEFAULT_OVERLAY_PROMPT,
        "refine": DEFAULT_REFINE_PROMPT,
    }[mode]


@dataclass
class InsertResult:
    """Bundle returned by :func:`insert_object`.

    ``composite_bytes`` is the final image the caller should display —
    it equals ``composite_bytes_relit`` when the relight pass ran, else
    ``composite_bytes_raw``.

    ``aux_bytes`` / ``aux_kind`` describe the *third image* sent to
    Gemini: a binary mask (mask mode), a pre-placed overlay (overlay
    mode), or the previous composite (refinement). Empty / ``None``
    when the call was a plain free-mode initial generation.
    """

    composite_bytes: bytes
    composite_mime: str
    composite_bytes_raw: bytes = b""
    composite_bytes_relit: bytes = b""
    aux_bytes: bytes = b""
    aux_kind: AuxKind | None = None
    masks: list[SegmentationMask] = field(default_factory=list)
    text: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guess_mime(path: Path) -> str:
    """MIME from extension; ``image/jpeg`` fallback (most common phone output)."""
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/jpeg"


def _polygon_to_pixels(
    polygon_norm: list[tuple[float, float]],
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Project normalized ``(u, v)`` vertices onto pixel coords + clamp.

    Clamping is defensive: the UI keeps points in range but a
    malformed payload shouldn't crash the rasterizer.
    """
    return [
        (
            max(0, min(width - 1, round(u * width))),
            max(0, min(height - 1, round(v * height))),
        )
        for u, v in polygon_norm
    ]


def _rasterize_polygon(
    scene_bytes: bytes,
    polygon_norm: list[tuple[float, float]],
) -> bytes:
    """Turn a normalized polygon into a binary PNG mask.

    White inside the polygon, black outside. Same width/height as the
    scene so the mask aligns pixel-for-pixel.
    """
    if len(polygon_norm) < 3:
        raise ValueError(f"Polygon needs at least 3 vertices, got {len(polygon_norm)}.")

    with Image.open(io.BytesIO(scene_bytes)) as scene:
        w, h = scene.size

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(_polygon_to_pixels(polygon_norm, w, h), fill=255)

    buf = io.BytesIO()
    mask.save(buf, format="PNG")
    return buf.getvalue()


def _build_overlay(
    scene_bytes: bytes,
    reference_bytes: bytes,
    polygon_norm: list[tuple[float, float]],
) -> bytes:
    """Pre-place the reference inside the polygon for overlay mode.

    Strategy: resize the reference to *cover* the polygon's bounding
    box (preserving aspect ratio), centre-crop to the bounding box,
    paste into a copy of the scene, then clip the result to the
    polygon's exact shape via the binary mask. The output is the same
    size as the scene and shows roughly where/how the reference
    should appear.

    Caveat: this is a bounding-box placement, not a perspective warp.
    For 4-vertex polygons we could do a true perspective transform
    via ``Image.transform(PERSPECTIVE, ...)``; that's a v2.
    """
    if len(polygon_norm) < 3:
        raise ValueError(
            f"Polygon needs at least 3 vertices, got {len(polygon_norm)}."
        )

    with Image.open(io.BytesIO(scene_bytes)) as raw_scene:
        scene = raw_scene.convert("RGB")
    with Image.open(io.BytesIO(reference_bytes)) as raw_ref:
        # Force RGB — alpha would mean reference logos paste with
        # transparency, which isn't useful for an opaque object.
        reference = raw_ref.convert("RGB")

    W, H = scene.size
    pixel_pts = _polygon_to_pixels(polygon_norm, W, H)

    xs = [p[0] for p in pixel_pts]
    ys = [p[1] for p in pixel_pts]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)

    # Cover-fit the reference to the bounding box, then centre-crop.
    rw, rh = reference.size
    scale = max(bw / rw, bh / rh)
    new_w = max(1, round(rw * scale))
    new_h = max(1, round(rh * scale))
    ref_resized = reference.resize((new_w, new_h), Image.LANCZOS)
    cx = (new_w - bw) // 2
    cy = (new_h - bh) // 2
    ref_cropped = ref_resized.crop((cx, cy, cx + bw, cy + bh))

    # Paste into a copy of the scene at the bounding-box position.
    overlay_full = scene.copy()
    overlay_full.paste(ref_cropped, (bx0, by0))

    # Clip the paste to the polygon's exact shape — outside the
    # polygon stays as the original scene.
    poly_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(poly_mask).polygon(pixel_pts, fill=255)
    final = Image.composite(overlay_full, scene, poly_mask)

    buf = io.BytesIO()
    final.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def insert_object(
    scene_path: str | Path,
    reference_path: str | Path,
    instruction: str,
    *,
    mode: Mode = "free",
    mask_polygon: list[tuple[float, float]] | None = None,
    system_prompt: str | None = None,
    previous_composite: bytes | None = None,
    previous_mime: str = "image/png",
    segmentation_prompts: list[str] | None = None,
    relight_prompt: str | None = None,
    replicate: Replicate | None = None,
    gemini: Gemini | None = None,
    falai: FalAI | None = None,
) -> InsertResult:
    """Run the insertion pipeline end-to-end.

    Parameters
    ----------
    scene_path, reference_path:
        Paths to the scene image and the reference object image.
    instruction:
        User's free-form description of the desired edit.
    mode:
        ``"free"`` (default), ``"mask"``, or ``"overlay"``. The latter
        two require ``mask_polygon``. See module docstring for the
        difference.
    mask_polygon:
        Optional list of normalized ``(u, v)`` vertices in ``[0, 1]``.
        Required when ``mode != "free"``; ignored when ``mode ==
        "free"``.
    system_prompt:
        Optional override for the mode's default system prompt. If
        ``None`` the default for the active mode (or refinement, if
        ``previous_composite`` is set) is used.
    previous_composite, previous_mime:
        When set, the call is treated as a refinement turn and ``mode``
        is effectively ignored — the previous composite goes as image 3.
    segmentation_prompts:
        Grounded-SAM labels for inspection (not fed to Gemini).
    relight_prompt:
        Optional IC-Light v2 prompt. Empty = skip relight.
    replicate, gemini, falai:
        Pre-built provider instances for dependency injection.
    """
    scene_path = Path(scene_path)
    reference_path = Path(reference_path)

    scene_bytes = scene_path.read_bytes()
    scene_mime = _guess_mime(scene_path)
    reference_bytes = reference_path.read_bytes()
    reference_mime = _guess_mime(reference_path)

    masks: list[SegmentationMask] = []
    if segmentation_prompts:
        rep = replicate or Replicate()
        seg_resp = await rep.segmentation.segment(
            scene_bytes, segmentation_prompts, mime_type=scene_mime
        )
        masks = seg_resp.masks

    # ------------------------------------------------------------------
    # Build the third image (if any) and pick the prompt template.
    # Refinement is the highest-priority branch.
    # ------------------------------------------------------------------
    aux_bytes = b""
    aux_mime = "image/png"
    aux_kind: AuxKind | None = None
    template_key: Mode | Literal["refine"]

    if previous_composite:
        template_key = "refine"
        aux_bytes = previous_composite
        aux_mime = previous_mime
        aux_kind = "previous"
    elif mode == "mask":
        if not mask_polygon:
            raise ValueError("mask mode requires a polygon (mask_polygon).")
        aux_bytes = _rasterize_polygon(scene_bytes, mask_polygon)
        aux_mime = "image/png"
        aux_kind = "mask"
        template_key = "mask"
    elif mode == "overlay":
        if not mask_polygon:
            raise ValueError("overlay mode requires a polygon (mask_polygon).")
        aux_bytes = _build_overlay(scene_bytes, reference_bytes, mask_polygon)
        aux_mime = "image/png"
        aux_kind = "overlay"
        template_key = "overlay"
    else:
        template_key = "free"

    template = system_prompt.strip() if system_prompt else default_system_prompt(template_key)
    full_instruction = f"{instruction}\n\n{template}"

    images: list[tuple[bytes, str]] = [
        (scene_bytes, scene_mime),
        (reference_bytes, reference_mime),
    ]
    if aux_bytes:
        images.append((aux_bytes, aux_mime))

    gem = gemini or Gemini()
    edit = await gem.image.edit(full_instruction, images)

    raw_bytes = edit.image_bytes
    raw_mime = edit.mime_type
    final_bytes = raw_bytes
    final_mime = raw_mime
    relit_bytes = b""

    if relight_prompt:
        fal = falai or FalAI()
        relight = await fal.relight.edit(relight_prompt, [(raw_bytes, raw_mime)])
        relit_bytes = relight.image_bytes
        final_bytes = relit_bytes
        final_mime = relight.mime_type

    return InsertResult(
        composite_bytes=final_bytes,
        composite_mime=final_mime,
        composite_bytes_raw=raw_bytes,
        composite_bytes_relit=relit_bytes,
        aux_bytes=aux_bytes if aux_kind in ("mask", "overlay") else b"",
        aux_kind=aux_kind if aux_kind in ("mask", "overlay") else None,
        masks=masks,
        text=edit.text,
    )
