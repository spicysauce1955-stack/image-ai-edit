from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from ..models.base import SegmentationMask
from ..providers import Gemini, Replicate


@dataclass
class InsertResult:
    composite_bytes: bytes
    composite_mime: str
    masks: list[SegmentationMask] = field(default_factory=list)
    text: str = ""


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/jpeg"


async def insert_object(
    scene_path: str | Path,
    reference_path: str | Path,
    instruction: str,
    *,
    segmentation_prompts: list[str] | None = None,
    replicate: Replicate | None = None,
    gemini: Gemini | None = None,
) -> InsertResult:
    """Run the POC pipeline: segment scene, then insert reference object via Gemini.

    Segmentation is best-effort context. The masks are saved for inspection but not
    fed as a binary mask channel — Gemini consumes them as multi-image conditioning,
    referenced from the prompt.
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

    full_instruction = (
        f"{instruction}\n\n"
        "Image 1 is the scene. Image 2 is the reference object to insert. "
        "Place the object photorealistically in the scene: respect the existing "
        "ground plane, perspective, occlusion (objects in front of it stay in front), "
        "and lighting/shadow direction of the scene. Preserve the object's shape, "
        "color, and texture from the reference. Output only the final composited image."
    )

    images: list[tuple[bytes, str]] = [
        (scene_bytes, scene_mime),
        (reference_bytes, reference_mime),
    ]

    gem = gemini or Gemini()
    edit = await gem.image.edit(full_instruction, images)

    return InsertResult(
        composite_bytes=edit.image_bytes,
        composite_mime=edit.mime_type,
        masks=masks,
        text=edit.text,
    )
