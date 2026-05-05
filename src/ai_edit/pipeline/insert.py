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
from ..providers import FalAI, Gemini, OpenAI, Replicate

Mode = Literal["free", "mask"]
MaskEngine = Literal["anydoor_chain", "gpt_fal", "anydoor", "openai", "flux_prepaste"]
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

# Mask mode is a TWO-STEP pipeline:
#
#   1. Pre-paste the reference object into the polygon shape on a copy
#      of the scene. This gives the diffusion model exact reference
#      pixels to harmonize rather than hallucinate from soft cues.
#   2. Run FLUX-Kontext-LoRA Inpaint on the prepasted image at LOW
#      strength (~0.45). Strength controls how much the model is
#      allowed to deviate from the input; low strength preserves most
#      of the pasted reference while smoothing seams, fixing
#      perspective, and adding shadows.
#
# Empirical comparison (yard.png + fence.jpg, see docs/results/):
#   - Direct FLUX inpaint w/ reference: visible slats but flat
#   - Pre-paste + low-strength refine:  exact slats + posts + texture
#
# So the prompt for mask mode is intentionally a *harmonize* prompt,
# not an *insert from scratch* prompt — the reference is already in
# the right place; the model's job is to integrate it cleanly.
DEFAULT_MASK_PROMPT = (
    "PRESERVATION-CRITICAL EDIT. Inside the WHITE region of the mask: "
    "render the object from the reference image — preserve its design, "
    "materials, colour, and every structural detail (slats, posts, "
    "panels, seams, ribs, edges, bolts, joints — whatever the reference "
    "shows) exactly. Re-render the object in the scene's perspective so "
    "it sits naturally in the masked area at the correct angle and "
    "scale. Match the scene's lighting and cast a soft realistic ground "
    "shadow.\n\n"
    "OUTSIDE the white region: every pixel must remain identical to the "
    "input scene. Do not redraw, repaint, recolour, restyle, or even "
    "slightly modify the lawn, the patio, planters, umbrellas, existing "
    "fences outside the white region, the house, the sky, or any "
    "trees/foliage. The only change in the entire output image is the "
    "new object inside the white region."
)

# The refinement-pass prompt used by the AnyDoor → gpt_fal chain.
# Crucial: "do NOT move" language to prevent gpt_fal from relocating
# the fence back to its semantic-prior location. The R2 sweep variant
# without this language relocated the AnyDoor result.
CHAIN_REFINE_PROMPT = (
    "Polish and sharpen the object that already exists inside the white "
    "masked region. Keep the object in the EXACT same position and at "
    "the same scale — do not move, duplicate, or relocate it. Use the "
    "reference image to make its surfaces, edges, materials, and texture "
    "crisper and more photorealistic. Improve the lighting integration "
    "with the surrounding scene and add a soft realistic ground shadow "
    "if appropriate. Outside the white region, every pixel must remain "
    "identical to the input scene."
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


def _build_openai_mask(
    scene_bytes: bytes,
    polygon_norm: list[tuple[float, float]],
) -> bytes:
    """Rasterize the polygon as the alpha-channel mask gpt-image-1 expects.

    OpenAI's image-edit API uses a different mask convention than most
    diffusion APIs:

    - Mask pixels with alpha = 0 (transparent) are inpainted.
    - Mask pixels with alpha = 255 (opaque) are preserved.

    So we build an RGBA image whose alpha channel is 0 inside the
    polygon and 255 outside. The RGB channels don't matter to the
    API; we use 0,0,0 for cleanliness.
    """
    if len(polygon_norm) < 3:
        raise ValueError(f"Polygon needs at least 3 vertices, got {len(polygon_norm)}.")

    with Image.open(io.BytesIO(scene_bytes)) as scene:
        w, h = scene.size

    alpha = Image.new("L", (w, h), 255)
    ImageDraw.Draw(alpha).polygon(_polygon_to_pixels(polygon_norm, w, h), fill=0)
    rgba = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rgba.putalpha(alpha)

    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    return buf.getvalue()


def _build_prepaste(
    scene_bytes: bytes,
    reference_bytes: bytes,
    polygon_norm: list[tuple[float, float]],
    *,
    reference_crop: tuple[float, float] | None = None,
) -> tuple[bytes, bytes]:
    """Pre-paste the reference into the polygon and return ``(prepasted, ref_for_paste)``.

    This is the heart of the high-fidelity insertion strategy. Empirically
    a single direct call to FLUX-Kontext-LoRA Inpaint produces a flat,
    "generalized" version of the reference object — slats and posts
    smoothed into a featureless panel — because diffusion inpainting
    hallucinates the masked region from scratch using the reference
    only as soft guidance.

    Pre-pasting the reference into the polygon BEFORE running the
    diffusion pass gives the model exact reference pixels to harmonize
    rather than hallucinate, and the subsequent low-strength
    (``strength=0.45``) inpaint preserves most of those pixels while
    smoothing the polygon edges, fixing perspective, and adding
    shadows.

    ``reference_crop`` (top, bottom) — both in ``[0, 1]`` — narrows the
    reference vertically before pasting. Useful when the reference
    photo has sky/grass/background above and below the object that
    would otherwise pollute the paste. ``None`` uses the whole
    reference.
    """
    with Image.open(io.BytesIO(scene_bytes)) as raw_scene:
        scene = raw_scene.convert("RGB")
    with Image.open(io.BytesIO(reference_bytes)) as raw_ref:
        ref = raw_ref.convert("RGB")

    W, H = scene.size
    pixel_pts = _polygon_to_pixels(polygon_norm, W, H)

    # Polygon bounding box in scene-pixel coords.
    xs = [p[0] for p in pixel_pts]
    ys = [p[1] for p in pixel_pts]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)

    # Optional vertical crop of the reference to isolate the object from
    # its own photo's background.
    if reference_crop:
        top, bot = reference_crop
        rH = ref.height
        ref = ref.crop((0, int(top * rH), ref.width, int(bot * rH)))

    rW, rH = ref.size
    # Cover-fit (preserve aspect ratio, crop excess) so the pasted
    # reference fully fills the bounding box without letterboxing.
    scale = max(bw / rW, bh / rH)
    new_w = max(1, round(rW * scale))
    new_h = max(1, round(rH * scale))
    ref_resized = ref.resize((new_w, new_h), Image.LANCZOS)
    cx = (new_w - bw) // 2
    cy = (new_h - bh) // 2
    ref_for_paste = ref_resized.crop((cx, cy, cx + bw, cy + bh))

    # Paste at the bbox position, then clip to the exact polygon shape
    # via the binary mask so areas outside the polygon stay scene-pure.
    overlay = scene.copy()
    overlay.paste(ref_for_paste, (bx0, by0))
    poly_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(poly_mask).polygon(pixel_pts, fill=255)
    prepasted = Image.composite(overlay, scene, poly_mask)

    pp_buf = io.BytesIO()
    prepasted.save(pp_buf, format="PNG")
    rf_buf = io.BytesIO()
    ref_for_paste.save(rf_buf, format="JPEG", quality=95)
    return pp_buf.getvalue(), rf_buf.getvalue()


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
    inpaint_guidance_scale: float = 3.5,
    inpaint_steps: int = 40,
    inpaint_strength: float = 0.45,
    reference_crop: tuple[float, float] | None = None,
    mask_engine: MaskEngine = "anydoor_chain",
    openai_quality: str = "high",
    openai: OpenAI | None = None,
    post_clip_to_mask: bool = False,
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
        (g=3.5, steps=40, s=0.45) were tuned empirically for the
        pre-paste + low-strength refine flow — see ``docs/results/``
        for the sweep. Strength controls how much the model deviates
        from the prepasted scene; low values preserve more of the
        reference's exact pixels.
    reference_crop:
        Optional ``(top, bottom)`` fractions in ``[0, 1]`` that
        vertically narrow the reference image before pasting. Useful
        when the reference photo has sky/grass/background above and
        below the object. ``None`` uses the whole reference.
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
        # Visual mask saved on the result for the UI's preview pane —
        # always white-on-black regardless of which engine runs, so
        # users see a familiar shape.
        aux_bytes = _rasterize_polygon(scene_bytes, mask_polygon)
        aux_kind = "mask"

        template = system_prompt.strip() if system_prompt else default_system_prompt("mask")

        # Optional post-clip helper. When enabled, composites the
        # model's output back onto the original scene through our
        # binary polygon mask, guaranteeing 100% pixel equality
        # outside the polygon. Disabled by default so callers see the
        # model's raw output and can decide whether the polygon
        # boundary should be enforced post-hoc — diffusion-style
        # clipping is a heavy hammer that hides interesting model
        # behaviour (e.g. shadows that *should* extend past the
        # polygon onto the ground).
        def _maybe_post_clip(model_output: bytes) -> bytes:
            if not post_clip_to_mask:
                return model_output
            with Image.open(io.BytesIO(model_output)) as raw:
                edited = raw.convert("RGB")
            with Image.open(io.BytesIO(scene_bytes)) as raw_scene:
                scene_img = raw_scene.convert("RGB")
            if edited.size != scene_img.size:
                edited = edited.resize(scene_img.size, Image.LANCZOS)
            poly_mask = Image.new("L", scene_img.size, 0)
            ImageDraw.Draw(poly_mask).polygon(
                _polygon_to_pixels(mask_polygon, *scene_img.size), fill=255
            )
            clipped = Image.composite(edited, scene_img, poly_mask)
            buf = io.BytesIO()
            clipped.save(buf, format="PNG")
            return buf.getvalue()

        if mask_engine == "anydoor_chain":
            # Two-pass pipeline: AnyDoor places the object correctly
            # in the polygon (gpt_fal can't — it ignores the mask
            # when the polygon conflicts with its semantic prior),
            # then gpt_fal refines the AnyDoor output to match the
            # reference's appearance and integrate lighting.
            #
            # The trick that makes the chain work: gpt_fal sees a
            # scene that ALREADY has a fence in the polygon (from
            # AnyDoor). Its semantic prior is satisfied — there's no
            # need to relocate — so it polishes what's there instead
            # of moving it. Verified empirically (variant-B sweep,
            # docs/results/18-*).
            rep = replicate or Replicate()

            # 1. Reference mask via Grounded-SAM (binary, not viz).
            seg_prompt = (instruction.split(".")[0])[:60].strip() or "object"
            seg_resp = await rep.segmentation.segment(
                reference_bytes, [seg_prompt], mime_type=reference_mime
            )
            ref_mask_bytes: bytes | None = None
            for m in seg_resp.masks:
                if m.label == seg_prompt:
                    ref_mask_bytes = m.image_bytes
                    break
            if ref_mask_bytes is None:
                raise RuntimeError(
                    f"Grounded-SAM produced no binary mask for the reference "
                    f"(prompt: {seg_prompt!r}). Got labels: "
                    f"{[m.label for m in seg_resp.masks]}"
                )

            # 2. AnyDoor placement pass.
            ad_resp = await rep.anydoor.edit(
                scene=(scene_bytes, scene_mime),
                scene_mask=(aux_bytes, "image/png"),
                reference=(reference_bytes, reference_mime),
                reference_mask=(ref_mask_bytes, "image/png"),
                steps=50,
                guidance_scale=4.5,
                control_strength=1.0,
            )

            # 3. gpt_fal refinement pass — feed AnyDoor's output as
            # the scene. The CHAIN_REFINE_PROMPT explicitly tells
            # gpt-image-1 not to relocate; without that the model
            # snaps the fence back to the back wall.
            fal = falai or FalAI()
            refine_resp = await fal.gpt_image.edit(
                scene=(ad_resp.image_bytes, "image/png"),
                mask=(aux_bytes, "image/png"),
                references=[(reference_bytes, reference_mime)],
                prompt=f"{instruction}. {CHAIN_REFINE_PROMPT}",
                input_fidelity="high",
                quality="high",
                image_size="1536x1024",
            )
            raw_bytes = _maybe_post_clip(refine_resp.image_bytes)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "gpt_fal":
            # OpenAI's gpt-image-1 routed through fal.ai's hosted
            # proxy. The model re-renders the masked region using
            # the reference for appearance and the scene for
            # perspective — visibly higher fidelity than FLUX.
            #
            # Empirically (sweep in docs/results/12-*) pinning
            # image_size to 1536x1024 (3:2, matching most phone
            # photos) instead of "auto" plus a strict preservation
            # prompt cuts outside-mask drift from ~24% to ~6.5%.
            fal = falai or FalAI()
            edit_resp = await fal.gpt_image.edit(
                scene=(scene_bytes, scene_mime),
                mask=(aux_bytes, "image/png"),
                references=[(reference_bytes, reference_mime)],
                prompt=f"{instruction}. {template}",
                input_fidelity="high",
                quality="high",
                image_size="1536x1024",
            )
            raw_bytes = _maybe_post_clip(edit_resp.image_bytes)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "anydoor":
            # AnyDoor (CVPR 2024) on Replicate. Designed exactly for
            # this primitive: re-render reference object inside a
            # mask in the target scene's perspective. Requires a
            # reference mask isolating the object — we generate one
            # automatically via Grounded-SAM (also Replicate, same
            # key) using "object" or the user's instruction as the
            # text prompt for the segmenter.
            rep = replicate or Replicate()
            mask_bytes = aux_bytes  # white-on-black scene mask

            # Auto-segment the reference object via Grounded-SAM. The
            # binary mask we want is labelled with the segmentation
            # prompt (see ReplicateGroundedSAM filename mapping). The
            # visualization with red bboxes is labelled "visualization"
            # — picking that as a mask was a silent bug that made
            # AnyDoor treat the whole reference as the object.
            seg_prompt = (instruction.split(".")[0])[:60].strip() or "object"
            seg_resp = await rep.segmentation.segment(
                reference_bytes, [seg_prompt], mime_type=reference_mime
            )
            ref_mask_bytes: bytes | None = None
            for m in seg_resp.masks:
                if m.label == seg_prompt:
                    ref_mask_bytes = m.image_bytes
                    break
            if ref_mask_bytes is None:
                raise RuntimeError(
                    f"Grounded-SAM produced no binary mask for reference "
                    f"(prompt: {seg_prompt!r}). Got labels: "
                    f"{[m.label for m in seg_resp.masks]}"
                )

            ad_resp = await rep.anydoor.edit(
                scene=(scene_bytes, scene_mime),
                scene_mask=(mask_bytes, "image/png"),
                reference=(reference_bytes, reference_mime),
                reference_mask=(ref_mask_bytes, "image/png"),
                steps=50,
                guidance_scale=4.5,
                control_strength=1.0,
            )
            raw_bytes = _maybe_post_clip(ad_resp.image_bytes)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "openai":
            # Native gpt-image-1 path through OpenAI directly.
            # Requires OPENAI_API_KEY billing to be unlocked.
            oai_mask = _build_openai_mask(scene_bytes, mask_polygon)
            oai = openai or OpenAI()
            oai_resp = await oai.image_edit.edit(
                scene=(scene_bytes, scene_mime),
                mask=(oai_mask, "image/png"),
                references=[(reference_bytes, reference_mime)],
                prompt=f"{instruction}. {template}",
                size="auto",
                quality=openai_quality,
            )
            raw_bytes = _maybe_post_clip(oai_resp.image_bytes)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "flux_prepaste":
            # Fallback for when OpenAI billing is exhausted. Pre-pastes
            # the reference into the polygon and runs FLUX-Kontext-LoRA
            # at low strength to harmonize. Lower fidelity than the
            # OpenAI path but always available on fal.ai.
            mask_bytes = _rasterize_polygon(scene_bytes, mask_polygon)
            prepasted_bytes, ref_for_paste_bytes = _build_prepaste(
                scene_bytes,
                reference_bytes,
                mask_polygon,
                reference_crop=reference_crop,
            )
            fal = falai or FalAI()
            edit_resp = await fal.inpaint.inpaint(
                scene=(prepasted_bytes, "image/png"),
                mask=(mask_bytes, "image/png"),
                reference=(ref_for_paste_bytes, "image/jpeg"),
                prompt=f"{instruction}. {template}",
                guidance_scale=inpaint_guidance_scale,
                num_inference_steps=inpaint_steps,
                strength=inpaint_strength,
            )
            raw_bytes = edit_resp.image_bytes
            raw_mime = edit_resp.mime_type
            edit_text = ""

        else:
            raise ValueError(f"Unknown mask_engine: {mask_engine!r}")

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
