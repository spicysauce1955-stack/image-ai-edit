"""Object-insertion orchestrator.

Glues the providers together into the M1–M5 POC pipeline:

::

    scene + reference + instruction
        │
        ├─► (optional) Replicate · Grounded-SAM
        │       → masks dumped for inspection only
        │
        ├─► Gemini · 2.5 Flash Image
        │       inputs: [scene, reference]
        │       output: raw composite
        │
        └─► (optional) fal.ai · IC-Light v2
                input: raw composite + relight prompt
                output: relit composite (sun direction, ground shadow)

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

The IC-Light step is opt-in via ``relight_prompt``. We always keep the
raw Gemini composite around (``composite_bytes_raw``) so callers can
A/B against the relit version.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from ..models.base import SegmentationMask
from ..providers import FalAI, Gemini, Replicate


@dataclass
class InsertResult:
    """Bundle returned by :func:`insert_object`.

    ``composite_bytes`` is the final image the caller should display —
    it equals ``composite_bytes_relit`` when the relight pass ran, else
    ``composite_bytes_raw``. The other two fields are kept around so
    callers can A/B compare or save both for inspection.

    ``masks`` is empty when segmentation was skipped. ``text`` carries
    any commentary Gemini emitted alongside the image (typically empty;
    useful for debugging).
    """

    composite_bytes: bytes
    composite_mime: str
    composite_bytes_raw: bytes = b""
    composite_bytes_relit: bytes = b""
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
    relight_prompt: str | None = None,
    replicate: Replicate | None = None,
    gemini: Gemini | None = None,
    falai: FalAI | None = None,
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
    relight_prompt:
        Optional relighting prompt for IC-Light, e.g.
        ``"warm afternoon sun from the right, soft ground shadows"``.
        When ``None`` the relight step is skipped and no fal.ai call is
        made.
    replicate, gemini, falai:
        Pre-built provider instances. Useful for dependency injection
        in tests; otherwise the function constructs them from env vars
        only when their step is actually invoked.

    Returns
    -------
    InsertResult
        ``composite_bytes`` is the final image (relit if requested,
        else raw). ``composite_bytes_raw`` is always the Gemini output;
        ``composite_bytes_relit`` is non-empty only when relighting ran.

    Notes
    -----
    Segmentation runs **before** the edit so that, in a future
    milestone, we can pre-process the masks (e.g. dilate, intersect,
    pick the largest region) and either feed them to a mask-aware
    insertion model or re-paste them onto Gemini's output for
    occlusion. For M3 they're saved purely for inspection.

    Relighting runs **after** the edit because IC-Light works on a
    finished composite — it doesn't know about the reference object,
    only the pixels Gemini produced.
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
    #
    # The shadow language is explicit and load-bearing: without it,
    # Gemini composites a flat, evenly-lit object that reads as pasted.
    # Asking it to *cast a ground shadow consistent with the scene's
    # sun direction* turned out to be enough lighting fidelity for the
    # POC, removing the need for a separate IC-Light pass that was
    # otherwise restyling the reference object.
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

    gem = gemini or Gemini()
    edit = await gem.image.edit(full_instruction, images)

    raw_bytes = edit.image_bytes
    raw_mime = edit.mime_type
    final_bytes = raw_bytes
    final_mime = raw_mime
    relit_bytes = b""

    # Relight is opt-in. Same provider-laziness contract as segmentation:
    # no fal.ai call (and no FAL_KEY required) unless the caller asks.
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
        masks=masks,
        text=edit.text,
    )
