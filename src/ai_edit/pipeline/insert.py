"""Object-insertion orchestrator.

Glues the providers together into the insertion pipeline:

::

    scene + reference + instruction + (optional) polygon
        │
        ├─► (optional) Replicate · Grounded-SAM
        │       → masks dumped for inspection only
        │
        ├─► Gemini · 2.5 Flash Image
        │       inputs: [scene, reference, mask?]
        │       output: raw composite
        │
        └─► (optional) fal.ai · IC-Light v2
                relit composite

Region / mask handling
----------------------
The user can constrain the placement to a polygon they draw in the UI.
The polygon arrives as a list of normalized ``(u, v)`` pairs in
``[0, 1]`` (so window resizes mid-draw don't matter). We rasterize it
via Pillow into a binary PNG matching the scene's natural pixel
dimensions, then pass that mask to Gemini as a third image and switch
the prompt into mask-aware mode.

Gemini does not consume a literal mask channel — only multi-image
conditioning + prompt — so the mask is *strong guidance*, not a hard
constraint. For a true alpha mask channel the next move is gpt-image-1
(see ``docs/contributing.md`` for the swap recipe); the existing
``mask_polygon`` argument carries straight over because it lives in
this orchestration layer rather than in the provider.

Important POC semantics for Grounded-SAM
----------------------------------------
The masks returned by Grounded-SAM are saved on the result for
inspection but **not** fed into Gemini. The user-drawn mask is the
authoritative signal; segmentation is only there if you want to
eyeball whether scene parsing is doing what you expect.
"""

from __future__ import annotations

import io
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from ..models.base import SegmentationMask
from ..providers import FalAI, Gemini, Replicate


@dataclass
class InsertResult:
    """Bundle returned by :func:`insert_object`.

    ``composite_bytes`` is the final image the caller should display —
    it equals ``composite_bytes_relit`` when the relight pass ran, else
    ``composite_bytes_raw``. ``mask_bytes`` is the rasterized polygon
    mask that was sent to Gemini (empty when no polygon was drawn);
    surfaced so the UI can show it next to the result for inspection.
    """

    composite_bytes: bytes
    composite_mime: str
    composite_bytes_raw: bytes = b""
    composite_bytes_relit: bytes = b""
    mask_bytes: bytes = b""
    masks: list[SegmentationMask] = field(default_factory=list)
    text: str = ""


def _guess_mime(path: Path) -> str:
    """Best-effort MIME detection from filename extension.

    Falls back to ``image/jpeg`` because that's the most common phone
    camera output and Gemini handles it without complaint.
    """
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/jpeg"


def _rasterize_polygon(
    scene_bytes: bytes,
    polygon_norm: list[tuple[float, float]],
) -> bytes:
    """Turn a normalized polygon into a binary PNG mask.

    Parameters
    ----------
    scene_bytes:
        The scene image bytes — used only to read the natural pixel
        dimensions so the mask comes out the same size.
    polygon_norm:
        Vertices as ``(u, v)`` pairs with ``u, v ∈ [0, 1]``.

    Returns
    -------
    bytes
        A PNG of mode ``L`` (single channel, 0–255) where white pixels
        mark the region the user drew. Same width/height as the scene.

    Raises
    ------
    ValueError:
        If the polygon has fewer than 3 vertices (Pillow accepts 2 but
        the result isn't a region).
    """
    if len(polygon_norm) < 3:
        raise ValueError(
            f"Polygon needs at least 3 vertices, got {len(polygon_norm)}."
        )

    with Image.open(io.BytesIO(scene_bytes)) as scene:
        w, h = scene.size

    # Clamp to the image bounds — UI should already do this, but a
    # malformed payload shouldn't crash the rasterizer.
    pixel_pts = [
        (max(0, min(w - 1, round(u * w))), max(0, min(h - 1, round(v * h))))
        for u, v in polygon_norm
    ]

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(pixel_pts, fill=255)

    buf = io.BytesIO()
    mask.save(buf, format="PNG")
    return buf.getvalue()


async def insert_object(
    scene_path: str | Path,
    reference_path: str | Path,
    instruction: str,
    *,
    mask_polygon: list[tuple[float, float]] | None = None,
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
    scene_path:
        Path to the scene image (the photo we're editing into).
    reference_path:
        Path to the reference object image (what to insert).
    instruction:
        Free-form description of the desired edit, e.g.
        ``"place this fence along the back edge of the lawn"``.
    mask_polygon:
        Optional list of normalized ``(u, v)`` vertices in ``[0, 1]``
        defining the region where the reference object should be
        placed. When provided, the pipeline rasterizes the polygon
        into a binary mask matching the scene's pixel dimensions and
        passes it to Gemini as a third image, switching the prompt
        into mask-aware mode.
    previous_composite:
        Optional bytes of a previous composite from this conversation.
        When provided the call is treated as a *refinement turn*: the
        previous composite is sent to Gemini as image 3, the prompt
        switches into refinement mode, and Gemini edits it rather than
        starting from scratch. Mutually exclusive with ``mask_polygon``
        in practice — refinement is about iterating on a result, not
        re-specifying the placement region. If both are provided the
        refinement branch wins.
    previous_mime:
        MIME type of ``previous_composite``. Defaults to ``image/png``.
    segmentation_prompts:
        Optional list of labels for Grounded-SAM. Masks are returned on
        the result for inspection but NOT fed into Gemini.
    relight_prompt:
        Optional IC-Light v2 prompt. Empty = skip relight.
    replicate, gemini, falai:
        Pre-built provider instances for dependency injection.

    Returns
    -------
    InsertResult
        See the dataclass for fields. ``mask_bytes`` is non-empty only
        when ``mask_polygon`` was provided.
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

    # Build the prompt. Three mutually exclusive modes — refinement
    # wins if both refinement and mask are passed (see docstring).
    mask_bytes = b""
    if previous_composite:
        full_instruction = (
            f"User refinement: {instruction}\n\n"
            "Image 1 is the original scene. Image 2 is the reference object. "
            "Image 3 is your previous attempt at the composite. "
            "Apply the user's refinement to image 3 — do not restart from scratch. "
            "Preserve everything that is already correct: object appearance from "
            "image 2, scene lighting and shadow direction from image 1, occlusion "
            "of foreground objects, and overall composition. Only change what the "
            "refinement explicitly asks for. Output only the updated composite."
        )
    elif mask_polygon:
        mask_bytes = _rasterize_polygon(scene_bytes, mask_polygon)
        full_instruction = (
            f"{instruction}\n\n"
            "Image 1 is the scene. Image 2 is the reference object to insert. "
            "Image 3 is a binary mask the user drew on the scene: WHITE pixels "
            "mark the exact region where the reference object should be placed; "
            "BLACK pixels must remain unchanged from image 1. "
            "Place the object photorealistically inside the white region, "
            "respecting perspective and the existing ground plane. Preserve "
            "the object's exact shape, color, material, and texture from "
            "image 2 — do not restyle or regenerate it. Match the scene's "
            "lighting: infer the sun direction from the existing shadows in "
            "image 1, then shade the inserted object accordingly and cast a "
            "soft, realistic ground shadow consistent with that direction. "
            "Foreground objects in image 1 that visually overlap the white "
            "region must remain in front of the inserted object. Output only "
            "the final composited image."
        )
    else:
        full_instruction = (
            f"{instruction}\n\n"
            "Image 1 is the scene. Image 2 is the reference object to insert. "
            "Place the object photorealistically in the scene: respect the existing "
            "ground plane, perspective, and occlusion (objects in front of the "
            "inserted region must remain in front). Match the scene's lighting: "
            "infer the sun direction from the existing shadows in image 1, then "
            "shade the inserted object accordingly and cast a soft, realistic "
            "ground shadow underneath it that falls in the same direction as the "
            "other shadows in the scene. Preserve the object's exact shape, "
            "color, material, and texture from image 2 — do not restyle or "
            "regenerate the object. Output only the final composited image."
        )

    images: list[tuple[bytes, str]] = [
        (scene_bytes, scene_mime),
        (reference_bytes, reference_mime),
    ]
    if previous_composite:
        images.append((previous_composite, previous_mime))
    elif mask_bytes:
        images.append((mask_bytes, "image/png"))

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
        mask_bytes=mask_bytes,
        masks=masks,
        text=edit.text,
    )
