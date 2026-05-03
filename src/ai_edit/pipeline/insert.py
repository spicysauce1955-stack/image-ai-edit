"""Object-insertion orchestrator.

Glues the providers together into the M1–M4 POC pipeline:

::

    scene + reference + instruction
        │
        ├─► (optional) Replicate · Grounded-SAM
        │       → masks dumped for inspection only
        │
        └─► Gemini · 2.5 Flash Image
                inputs: [scene, reference]
                output: composited image

Important POC semantics
-----------------------
The masks returned by Grounded-SAM are **not** fed into Gemini as a
binary mask channel. Gemini's multi-image API doesn't accept a literal
mask — only multi-image conditioning + prompt — so for the first POC we
let Gemini infer the placement from the scene + reference + instruction
alone.

Why dump the masks at all then? Because we need to *eyeball* whether
Grounded-SAM is identifying the right regions before committing to one
of the upgrade paths in ``docs/poc-plan.md``:

- **M4**: re-paste foreground masks (e.g. trees) on top of Gemini's
  output via PIL to enforce occlusion.
- **Vendor swap**: if Gemini ignores the placement, switch insertion to
  OpenAI gpt-image-1 (which *does* take a mask) using one of the
  Grounded-SAM masks as input.

Both paths require those masks to already be available.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from ..models.base import SegmentationMask
from ..providers import Gemini, Replicate


@dataclass
class InsertResult:
    """Bundle returned by :func:`insert_object`.

    ``masks`` is empty when segmentation was skipped. ``text`` carries
    any commentary Gemini emitted alongside the image (typically
    empty; useful for debugging).
    """

    composite_bytes: bytes
    composite_mime: str
    masks: list[SegmentationMask] = field(default_factory=list)
    text: str = ""


def _guess_mime(path: Path) -> str:
    """Best-effort MIME detection from filename extension.

    Falls back to ``image/jpeg`` because that's the most common phone
    camera output and Gemini handles it without complaint.
    """
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
    """Run the POC pipeline end-to-end.

    Parameters
    ----------
    scene_path:
        Path to the scene image (the photo we're editing into).
    reference_path:
        Path to the reference object image (what to insert).
    instruction:
        Free-form description of the desired edit, e.g.
        ``"place this fence along the back edge of the lawn"``.
    segmentation_prompts:
        Optional list of labels (e.g. ``["ground", "trees", "sky"]``) to
        run Grounded-SAM against. When ``None`` the segmentation step
        is skipped entirely and no Replicate call is made.
    replicate, gemini:
        Pre-built provider instances. Useful for dependency injection
        in tests; otherwise the function constructs them from env vars.

    Returns
    -------
    InsertResult
        ``composite_bytes`` is the final image, ``masks`` are the
        per-label masks if segmentation ran (otherwise empty).

    Notes
    -----
    Segmentation runs **before** the edit so that, in a future
    milestone, we can pre-process the masks (e.g. dilate, intersect,
    pick the largest region) and either feed them to a mask-aware
    insertion model or re-paste them onto Gemini's output for
    occlusion. For M3 they're saved purely for inspection.
    """
    scene_path = Path(scene_path)
    reference_path = Path(reference_path)

    scene_bytes = scene_path.read_bytes()
    scene_mime = _guess_mime(scene_path)
    reference_bytes = reference_path.read_bytes()
    reference_mime = _guess_mime(reference_path)

    # Segmentation is opt-in. When skipped we don't even instantiate
    # the Replicate provider, which means callers without a Replicate
    # key can still run the insertion path.
    masks: list[SegmentationMask] = []
    if segmentation_prompts:
        rep = replicate or Replicate()
        seg_resp = await rep.segmentation.segment(
            scene_bytes, segmentation_prompts, mime_type=scene_mime
        )
        masks = seg_resp.masks

    # Standard prompt suffix telling Gemini how to interpret the image
    # positions. Kept here rather than in the provider so the provider
    # stays generic across use cases.
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
