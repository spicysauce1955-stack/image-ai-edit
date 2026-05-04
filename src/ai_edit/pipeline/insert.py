"""Object-insertion orchestrator.

Two routes through the pipeline depending on whether the caller drew
a polygon to constrain placement.

::

    free mode
    ─────────
    scene + reference + instruction
        │
        ├─► (optional) Replicate · Grounded-SAM
        │       → masks dumped for inspection only
        │
        ├─► Gemini · 2.5 Flash Image
        │       inputs: [scene, reference]
        │       output: composite (model picks placement)
        │
        └─► (optional) fal.ai · IC-Light v2
                relit composite

::

    mask mode
    ─────────
    scene + reference + polygon + instruction
        │
        ├─► rasterize polygon → binary PNG (white = fill, black = preserve)
        │
        ├─► fal.ai · FLUX-Kontext-LoRA Inpaint
        │       native fields: image_url, mask_url, reference_image_url, prompt
        │       output: composite — mask is a HARD constraint (verified at
        │               99.8% pixel-equality outside the polygon)
        │
        └─► (optional) fal.ai · IC-Light v2

Why two providers
-----------------
Gemini 2.5 Flash Image is excellent for free-form placement (it
reasons about the whole scene and infers good positions) but doesn't
consume a literal alpha mask — empirically it ignores binary mask
hints and rewrites global semantics ("fence" everywhere it sees one).

FLUX-Kontext-LoRA Inpaint on fal.ai accepts ``mask_url`` as a true
alpha channel: pixels black in the mask are preserved exactly. It
also accepts a separate ``reference_image_url`` so we can put the
user's specific fence in the inserted region rather than a generic
hallucination.

Refinement mode (``previous_composite`` set) always goes through
Gemini regardless of placement mode — refinement is iterative editing
on a finished composite, not re-specifying a placement region.

System prompt
-------------
Each mode has a default system prompt template exposed as a constant
below and via :func:`default_system_prompt`. Callers can override per
request by passing ``system_prompt=...``. The ``/api/defaults`` server
endpoint serves these defaults to the UI's textarea.
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

Mode = Literal["free", "mask"]
AuxKind = Literal["mask", "previous"]


# ---------------------------------------------------------------------------
# Default system prompts
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

# Mask mode goes to FLUX-Kontext-LoRA, not Gemini. The mask is a hard
# alpha constraint at the provider level, so the prompt is purely
# about object identity and integration. Empirically, the most
# effective phrasing tells FLUX to *preserve specific structural
# details* of the reference — slats/posts/texture by name — rather
# than just "use the reference". Without this kind of language the
# model produces a flat featureless inpaint of roughly the right
# colour. The "exactly as shown in the reference image" phrase is the
# key unlock; combined with guidance_scale=4.5 it carries the
# reference's structure into the output.
DEFAULT_MASK_PROMPT = (
    "Insert the object photorealistically inside the masked region. "
    "Reproduce the object exactly as shown in the reference image — "
    "preserve every structural detail (slats, posts, panels, seams, "
    "ribs, edges, bolts, joints, whatever the reference shows), "
    "preserve the exact colour and material, and preserve the surface "
    "texture and finish. Do not flatten, smooth, or generalize the "
    "object. Match the scene's perspective and the existing ground "
    "plane. Match the scene's lighting: infer the sun direction from "
    "the existing shadows in the scene and shade the object "
    "accordingly, casting a soft realistic ground shadow consistent "
    "with that direction."
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
    """Return the default system prompt for a given mode."""
    return {
        "free": DEFAULT_FREE_PROMPT,
        "mask": DEFAULT_MASK_PROMPT,
        "refine": DEFAULT_REFINE_PROMPT,
    }[mode]


@dataclass
class InsertResult:
    """Bundle returned by :func:`insert_object`.

    ``aux_bytes`` is the binary mask image (mask mode) or empty
    (free / refine). UI uses it for the side-by-side preview.
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
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/jpeg"


def _polygon_to_pixels(
    polygon_norm: list[tuple[float, float]],
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Project normalized ``(u, v)`` vertices onto pixel coords + clamp."""
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
    scene so the mask aligns pixel-for-pixel — FLUX rejects mismatched
    dimensions.
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
    inpaint_guidance_scale: float = 4.5,
    inpaint_steps: int = 40,
    inpaint_strength: float = 0.92,
) -> InsertResult:
    """Run the insertion pipeline end-to-end.

    Parameters
    ----------
    scene_path, reference_path:
        Paths to the scene image and the reference object image.
    instruction:
        User's free-form description.
    mode:
        ``"free"`` (Gemini) or ``"mask"`` (FLUX-Kontext-LoRA Inpaint).
        ``"mask"`` requires ``mask_polygon``.
    mask_polygon:
        Optional list of normalized ``(u, v)`` vertices in ``[0, 1]``.
        Required when ``mode == "mask"``.
    system_prompt:
        Override the active mode's default system prompt. ``None`` =
        use the default.
    previous_composite, previous_mime:
        When set, pipeline runs in refinement mode — Gemini edits the
        previous composite. Overrides ``mode``.
    segmentation_prompts:
        Grounded-SAM labels for inspection only.
    relight_prompt:
        Optional IC-Light v2 prompt for a post-processing pass.
    replicate, gemini, falai:
        Provider DI hooks.
    inpaint_guidance_scale, inpaint_steps, inpaint_strength:
        Forwarded to FLUX-Kontext-LoRA when in mask mode. Defaults
        (g=4.5, steps=40, s=0.92) were tuned empirically — see
        ``docs/results/`` for the comparison sweep. Turn guidance up
        further for stricter prompt adherence at the cost of variety.
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

    aux_bytes = b""
    aux_kind: AuxKind | None = None

    if previous_composite:
        # Refinement turn — always Gemini, ignores `mode`.
        template = system_prompt.strip() if system_prompt else default_system_prompt("refine")
        full_instruction = f"User refinement: {instruction}\n\n{template}"
        gem = gemini or Gemini()
        edit = await gem.image.edit(
            full_instruction,
            [
                (scene_bytes, scene_mime),
                (reference_bytes, reference_mime),
                (previous_composite, previous_mime),
            ],
        )
        aux_bytes = previous_composite
        aux_kind = "previous"
        raw_bytes = edit.image_bytes
        raw_mime = edit.mime_type
        edit_text = edit.text

    elif mode == "mask":
        if not mask_polygon:
            raise ValueError("mask mode requires mask_polygon.")
        mask_bytes = _rasterize_polygon(scene_bytes, mask_polygon)
        aux_bytes = mask_bytes
        aux_kind = "mask"

        # FLUX gets a focused prompt — the system_prompt acts as
        # supplemental guidance, the user's instruction is the lead.
        template = system_prompt.strip() if system_prompt else default_system_prompt("mask")
        flux_prompt = f"{instruction}. {template}"

        fal = falai or FalAI()
        edit_resp = await fal.inpaint.inpaint(
            scene=(scene_bytes, scene_mime),
            mask=(mask_bytes, "image/png"),
            reference=(reference_bytes, reference_mime),
            prompt=flux_prompt,
            guidance_scale=inpaint_guidance_scale,
            num_inference_steps=inpaint_steps,
            strength=inpaint_strength,
        )
        raw_bytes = edit_resp.image_bytes
        raw_mime = edit_resp.mime_type
        edit_text = ""

    else:  # mode == "free"
        template = system_prompt.strip() if system_prompt else default_system_prompt("free")
        full_instruction = f"{instruction}\n\n{template}"
        gem = gemini or Gemini()
        edit = await gem.image.edit(
            full_instruction,
            [(scene_bytes, scene_mime), (reference_bytes, reference_mime)],
        )
        raw_bytes = edit.image_bytes
        raw_mime = edit.mime_type
        edit_text = edit.text

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
        aux_bytes=aux_bytes if aux_kind == "mask" else b"",
        aux_kind=aux_kind if aux_kind == "mask" else None,
        masks=masks,
        text=edit_text,
    )
