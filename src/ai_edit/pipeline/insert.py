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

Mode = Literal["free", "mask", "overlay"]
MaskEngine = Literal[
    "gpt_image_2",        # default — OpenAI's April 2026 model; instruction-following solves semantic prior
    "gemini_translucent", # pre-paste reference at 55% alpha → Nano Banana Pro
    "flux_ref_inpaint",   # fal flux-general/inpainting with native reference_image_url
    "gemini_crop",        # crop polygon bbox+pad → Nano Banana edit → feathered reassemble
    "anydoor_chain",      # AnyDoor placement + gpt-image-1 refinement
    "gpt_fal",            # gpt-image-1 alone (ignores polygon outside semantic prior)
    "anydoor",            # AnyDoor alone
    "openai",             # OpenAI direct
    "flux_prepaste",      # FLUX prepaste fallback
]
AuxKind = Literal["mask", "overlay", "previous"]


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


def _build_poles_mask(
    scene_bytes: bytes,
    poles: list[tuple[float, float]],
    *,
    section_height_norm: float = 0.18,
    pole_section_lengths: list[float | None] | None = None,
    post_width_norm: float = 0.012,
) -> bytes:
    """Rasterize a fence-from-poles binary PNG mask matching scene dims.

    The basic unit of a fence is two poles + a section between them.
    The user places poles at the BASE of the fence (where the post
    meets the ground); the rendered mask covers both:

      - one post column at each pole, ``post_width_norm * scene_W``
        pixels wide, extending UP from the click by ``section_height``.
      - one section parallelogram between every consecutive pair of
        poles, with the bottom edge along the line connecting their
        bases and the top edge ``section_height`` pixels above.

    ``pole_section_lengths`` (optional, parallel to ``poles``) gives a
    per-pole maximum section length in normalized image units. The
    section between pole_i and pole_{i+1} uses the SMALLER of the two
    poles' caps (a real-world fencing constraint — a pole only
    supports panels up to its rated length). When the actual distance
    between the two clicks exceeds the cap, the section is drawn
    truncated to ``cap`` pixels along the line from pole_i; the
    remaining gap signals to the user that an intermediate pole is
    needed. ``None`` for a pole means "no cap".
    """
    if len(poles) < 2:
        raise ValueError(f"Need at least 2 poles, got {len(poles)}.")
    if pole_section_lengths is not None and len(pole_section_lengths) != len(poles):
        raise ValueError(
            f"pole_section_lengths length {len(pole_section_lengths)} "
            f"!= poles length {len(poles)}."
        )

    with Image.open(io.BytesIO(scene_bytes)) as scene:
        W, H = scene.size

    section_height_px = max(4, int(section_height_norm * H))
    post_width_px = max(2, int(post_width_norm * W))

    # Convert normalized poles to clamped pixel coords.
    pole_px = [
        (
            max(0, min(W - 1, round(u * W))),
            max(0, min(H - 1, round(v * H))),
        )
        for u, v in poles
    ]

    mask = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(mask)

    # Sections between consecutive poles.
    for i in range(len(pole_px) - 1):
        p1 = pole_px[i]
        p2 = pole_px[i + 1]

        # Min of both endpoints' max section lengths (in pixels).
        cap_px: int | None = None
        if pole_section_lengths is not None:
            caps_norm = [pole_section_lengths[i], pole_section_lengths[i + 1]]
            caps_norm_clean = [c for c in caps_norm if c is not None]
            if caps_norm_clean:
                cap_px = max(1, int(min(caps_norm_clean) * W))

        if cap_px is not None:
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            d = (dx * dx + dy * dy) ** 0.5
            if d > cap_px and d > 0:
                ratio = cap_px / d
                p2 = (round(p1[0] + dx * ratio), round(p1[1] + dy * ratio))

        # Section parallelogram: bottom along line connecting bases,
        # top shifted up by section_height. Constant vertical
        # height in image space — the model handles perspective.
        section_quad = [
            (p1[0], p1[1]),
            (p2[0], p2[1]),
            (p2[0], max(0, p2[1] - section_height_px)),
            (p1[0], max(0, p1[1] - section_height_px)),
        ]
        draw.polygon(section_quad, fill=255)

    # Post columns at each pole.
    half_post = post_width_px // 2
    for px, py in pole_px:
        draw.rectangle(
            [
                (max(0, px - half_post), max(0, py - section_height_px)),
                (min(W - 1, px + half_post), py),
            ],
            fill=255,
        )

    buf = io.BytesIO()
    mask.save(buf, format="PNG")
    return buf.getvalue()


def _perspective_coeffs(
    src: list[tuple[float, float]],
    dst: list[tuple[float, float]],
) -> list[float]:
    """8 perspective coefficients for ``Image.transform(..., PERSPECTIVE)``.

    The PIL transform interprets coefficients as the *inverse* mapping
    from output coords back to source: for output pixel ``(x, y)`` it
    samples the source at:

        src_x = (a*x + b*y + c) / (g*x + h*y + 1)
        src_y = (d*x + e*y + f) / (g*x + h*y + 1)

    To map an output quadrilateral (``dst``) back to source-rectangle
    corners (``src``) we solve the standard 8-equation linear system.
    """
    import numpy as _np

    matrix = []
    for s, d in zip(src, dst):
        matrix.append([d[0], d[1], 1, 0, 0, 0, -s[0] * d[0], -s[0] * d[1]])
        matrix.append([0, 0, 0, d[0], d[1], 1, -s[1] * d[0], -s[1] * d[1]])
    A = _np.array(matrix, dtype=_np.float64)
    B = _np.array([c for s in src for c in s], dtype=_np.float64)
    return list(_np.linalg.solve(A, B))


def _warp_reference_to_quad(
    reference: Image.Image,
    quad_corners: list[tuple[int, int]],
    canvas_size: tuple[int, int],
) -> Image.Image:
    """Perspective-warp ``reference`` into ``quad_corners`` on a canvas.

    ``quad_corners`` are 4 points in OUTPUT pixel space — ordered
    bl, br, tr, tl (matching the section parallelogram corners). The
    full reference rectangle gets perspective-transformed so its four
    corners land on those four points; pixels outside the polygon are
    transparent.
    """
    rW, rH = reference.size
    src = [(0, rH), (rW, rH), (rW, 0), (0, 0)]  # bl, br, tr, tl in ref space
    coeffs = _perspective_coeffs(src, [(d[0], d[1]) for d in quad_corners])

    warped = reference.convert("RGBA").transform(
        canvas_size,
        Image.PERSPECTIVE,
        coeffs,
        Image.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    # Clip outside the quad — perspective transform fills the whole
    # canvas with extrapolated samples; we only want the parallelogram.
    poly_mask = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(poly_mask).polygon(quad_corners, fill=255)
    transparent = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    return Image.composite(warped, transparent, poly_mask)


# Marker colour for the overlay mode. Magenta (255, 0, 220) — chosen
# because it almost never naturally occurs in outdoor scenes, so the
# model unambiguously recognises it as an annotation rather than a
# scene element to preserve.
_OVERLAY_MARKER_RGB = (255, 0, 220)


def _build_poles_overlay(
    scene_bytes: bytes,
    poles: list[tuple[float, float]],
    *,
    section_height_norm: float = 0.18,
    pole_section_lengths: list[float | None] | None = None,
    post_width_norm: float = 0.012,
    alpha: float = 0.55,
) -> bytes:
    """Draw a fence-shaped colored marker on a copy of the scene.

    The marker is the union of:
      - section parallelograms between consecutive poles
      - post columns at each pole

    Filled in translucent magenta with a solid magenta outline. The
    reference fence image is NOT pre-pasted here — it goes to the
    model as a separate image. The marker tells the model *where*
    the fence should appear; the reference tells it *what* the fence
    looks like.

    ``alpha`` controls the marker's translucency (0.0 = invisible,
    1.0 = solid). 0.55 is a good default: visible enough that the
    model picks up the placement intent, transparent enough that
    underlying scene context (lawn texture, lighting cues) still
    informs the render.

    Per-pole section length caps work the same way as in
    :func:`_build_poles_mask`.
    """
    if len(poles) < 2:
        raise ValueError(f"Need at least 2 poles, got {len(poles)}.")

    with Image.open(io.BytesIO(scene_bytes)) as raw_scene:
        scene = raw_scene.convert("RGBA")

    W, H = scene.size
    section_height_px = max(4, int(section_height_norm * H))
    post_width_px = max(2, int(post_width_norm * W))
    pole_px = [
        (
            max(0, min(W - 1, round(u * W))),
            max(0, min(H - 1, round(v * H))),
        )
        for u, v in poles
    ]

    fill_alpha = max(0, min(255, int(alpha * 255)))
    fill_rgba = (*_OVERLAY_MARKER_RGB, fill_alpha)
    line_rgba = (*_OVERLAY_MARKER_RGB, 255)
    line_w = max(2, min(W, H) // 200)

    fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    line_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(fill_layer)
    ldraw = ImageDraw.Draw(line_layer)

    # Section parallelograms.
    for i in range(len(pole_px) - 1):
        p1 = pole_px[i]
        p2 = pole_px[i + 1]

        cap_px: int | None = None
        if pole_section_lengths is not None:
            caps = [pole_section_lengths[i], pole_section_lengths[i + 1]]
            caps_clean = [c for c in caps if c is not None]
            if caps_clean:
                cap_px = max(1, int(min(caps_clean) * W))
        if cap_px is not None:
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            d = (dx * dx + dy * dy) ** 0.5
            if d > cap_px and d > 0:
                ratio = cap_px / d
                p2 = (round(p1[0] + dx * ratio), round(p1[1] + dy * ratio))

        if abs(p2[0] - p1[0]) + abs(p2[1] - p1[1]) < 2:
            continue

        quad = [
            (p1[0], p1[1]),
            (p2[0], p2[1]),
            (p2[0], max(0, p2[1] - section_height_px)),
            (p1[0], max(0, p1[1] - section_height_px)),
        ]
        fdraw.polygon(quad, fill=fill_rgba)
        ldraw.polygon(quad, outline=line_rgba, width=line_w)

    # Post columns at each pole (rendered solid for visibility).
    half_post = post_width_px // 2
    for px, py in pole_px:
        rect = [
            (max(0, px - half_post), max(0, py - section_height_px)),
            (min(W - 1, px + half_post), py),
        ]
        fdraw.rectangle(rect, fill=line_rgba)

    composite = Image.alpha_composite(
        Image.alpha_composite(scene, fill_layer), line_layer
    )
    out = composite.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _build_translucent_prepaste(
    scene_bytes: bytes,
    reference_bytes: bytes,
    polygon_norm: list[tuple[float, float]],
    *,
    alpha: float = 0.55,
    reference_crop: tuple[float, float] | None = None,
) -> bytes:
    """Pre-paste the reference into the polygon at fractional alpha.

    Empirically (May 2026 sweep at docs/results/26-translucent-*) this
    is the strongest input for Gemini-family models on hard polygons:

    - At ``alpha=0.20-0.35``: the reference is too faint, so Gemini
      ignores the polygon and relocates the object to its semantic
      prior location.
    - At ``alpha=0.55``: the reference is clearly visible at the
      polygon location (giving Gemini a strong spatial cue) but
      faded enough that Gemini understands it should *re-render*
      rather than copy-paste. The model produces a crisp object
      inside the polygon and leaves the rest of the scene alone.
    - At ``alpha=0.75-0.95``: the reference looks "correct enough" that
      Gemini decides to extend the same style globally, replacing
      other instances of the object class throughout the scene.

    The single output image carries three signals at once:
    *where* (the visible reference at the polygon), *what* (the
    reference identity at low opacity), and *what to preserve* (the
    scene visible everywhere else). This is why it works where pure
    binary masks and pure colored markers don't.
    """
    if len(polygon_norm) < 3:
        raise ValueError(f"Polygon needs at least 3 vertices, got {len(polygon_norm)}.")
    alpha = max(0.0, min(1.0, alpha))

    with Image.open(io.BytesIO(scene_bytes)) as raw:
        scene = raw.convert("RGB")
    with Image.open(io.BytesIO(reference_bytes)) as raw_ref:
        ref = raw_ref.convert("RGB")

    if reference_crop:
        top, bot = reference_crop
        rH = ref.height
        ref = ref.crop((0, int(top * rH), ref.width, int(bot * rH)))

    W, H = scene.size
    pixel_pts = _polygon_to_pixels(polygon_norm, W, H)
    xs = [p[0] for p in pixel_pts]
    ys = [p[1] for p in pixel_pts]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)

    # Cover-fit the reference to the polygon's bounding box.
    rW, rH = ref.size
    sf = max(bw / rW, bh / rH)
    nW, nH = max(1, round(rW * sf)), max(1, round(rH * sf))
    ref_resized = ref.resize((nW, nH), Image.LANCZOS)
    cx, cy = (nW - bw) // 2, (nH - bh) // 2
    ref_for_paste = ref_resized.crop((cx, cy, cx + bw, cy + bh))

    # Build a polygon-shaped overlay containing the resized reference.
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay.paste(ref_for_paste, (bx0, by0))
    poly_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(poly_mask).polygon(pixel_pts, fill=255)
    clipped = Image.composite(overlay, Image.new("RGBA", (W, H), (0, 0, 0, 0)), poly_mask)

    # Multiply the alpha channel by the desired fraction.
    a_band = clipped.split()[3]
    a_band = a_band.point(lambda x, frac=alpha: int(x * frac))
    clipped.putalpha(a_band)

    base = scene.convert("RGBA")
    result = Image.alpha_composite(base, clipped).convert("RGB")

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


def _crop_with_marker(
    scene_bytes: bytes,
    polygon_norm: list[tuple[float, float]],
    *,
    pad_frac: float = 0.30,
) -> tuple[bytes, tuple[int, int, int, int]]:
    """Crop the scene around the polygon and burn a marker on the crop.

    Returns ``(crop_png_bytes, (px0, py0, px1, py1))``. The crop is the
    polygon's bounding box expanded by ``pad_frac`` on each side
    (clamped to the scene) so the model sees enough surrounding
    context (ground line, lighting) to integrate cleanly.

    A magenta polygon (translucent fill + solid outline) is drawn on
    the cropped scene so the model knows where to place the object —
    crucially, *the cropped view contains no other instances of the
    target object class*, so the model can't relocate to its semantic
    prior. That's the trick that makes this pipeline work where
    direct mask-based pipelines silently relocate the object.
    """
    if len(polygon_norm) < 3:
        raise ValueError(f"Polygon needs at least 3 vertices, got {len(polygon_norm)}.")

    with Image.open(io.BytesIO(scene_bytes)) as raw:
        scene = raw.convert("RGB")
    W, H = scene.size

    pix = _polygon_to_pixels(polygon_norm, W, H)
    xs = [p[0] for p in pix]
    ys = [p[1] for p in pix]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    bw, bh = bx1 - bx0, by1 - by0

    px0 = max(0, bx0 - int(bw * pad_frac))
    py0 = max(0, by0 - int(bh * pad_frac))
    px1 = min(W, bx1 + int(bw * pad_frac))
    py1 = min(H, by1 + int(bh * pad_frac))

    crop = scene.crop((px0, py0, px1, py1)).convert("RGBA")
    local = [(p[0] - px0, p[1] - py0) for p in pix]

    fill_layer = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    ImageDraw.Draw(fill_layer).polygon(local, fill=(255, 0, 220, 130))
    line_layer = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    ImageDraw.Draw(line_layer).polygon(local, outline=(255, 0, 220, 255), width=4)

    composite = Image.alpha_composite(Image.alpha_composite(crop, fill_layer), line_layer)
    out = composite.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), (px0, py0, px1, py1)


def _reassemble_crop(
    scene_bytes: bytes,
    edited_crop_bytes: bytes,
    crop_box: tuple[int, int, int, int],
    *,
    feather_frac: float = 1 / 12,
) -> bytes:
    """Composite the edited crop back into the scene with a feathered mask.

    The mask is a soft-edged rectangle (Gaussian-blurred) inset from
    the crop boundary, so the edit blends into the surrounding
    untouched scene without visible seams. Pixels outside the crop
    region are byte-identical to the original scene.
    """
    from PIL import ImageFilter

    with Image.open(io.BytesIO(scene_bytes)) as raw:
        scene = raw.convert("RGB")
    with Image.open(io.BytesIO(edited_crop_bytes)) as raw_edited:
        edited = raw_edited.convert("RGB")

    px0, py0, px1, py1 = crop_box
    target_size = (px1 - px0, py1 - py0)
    if edited.size != target_size:
        edited = edited.resize(target_size, Image.LANCZOS)

    inner_pad = max(8, int(min(target_size) * feather_frac))
    fmask = Image.new("L", target_size, 0)
    ImageDraw.Draw(fmask).rectangle(
        (inner_pad, inner_pad, target_size[0] - inner_pad, target_size[1] - inner_pad),
        fill=255,
    )
    fmask = fmask.filter(ImageFilter.GaussianBlur(radius=inner_pad / 1.5))

    blended = Image.composite(edited, scene.crop(crop_box), fmask)
    out = scene.copy()
    out.paste(blended, (px0, py0))

    buf = io.BytesIO()
    out.save(buf, format="PNG")
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
    poles: list[tuple[float, float]] | None = None,
    pole_section_height: float = 0.18,
    pole_section_lengths: list[float | None] | None = None,
    pole_post_width: float = 0.012,
    overlay_alpha: float = 0.55,
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
    mask_engine: MaskEngine = "gpt_image_2",
    gpt_image_2_quality: str = "high",
    translucent_alpha: float = 0.55,
    translucent_model: str | None = None,
    flux_ref_strength: float = 0.65,
    flux_ref_steps: int = 50,
    flux_ref_guidance: float = 5.0,
    gemini_crop_pad_frac: float = 0.30,
    gemini_crop_model: str | None = None,
    openai_quality: str = "high",
    openai: OpenAI | None = None,
    post_clip_to_mask: bool = True,
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

    elif mode in ("mask", "overlay"):
        # Both modes share the same placement primitive (poles or
        # legacy polygon) and the same downstream engines. They
        # differ only in what gets sent as the SCENE input:
        #   - mask:    original scene + binary mask
        #   - overlay: scene with reference fence pre-pasted at
        #              translucent alpha into the section quads
        #              (perspective-warped per section), + the same
        #              binary mask. Gives the model a visible
        #              preview of placement + identity together.
        if poles:
            binary_mask_bytes = _build_poles_mask(
                scene_bytes,
                poles,
                section_height_norm=pole_section_height,
                pole_section_lengths=pole_section_lengths,
                post_width_norm=pole_post_width,
            )
            mask_polygon = (
                [(u, v) for u, v in poles]
                + [(u, max(0.0, v - pole_section_height)) for u, v in reversed(poles)]
            )
        elif mask_polygon:
            binary_mask_bytes = _rasterize_polygon(scene_bytes, mask_polygon)
        else:
            raise ValueError(f"{mode!r} mode requires either poles or mask_polygon.")

        if mode == "overlay":
            if not poles:
                raise ValueError("overlay mode requires poles (marker uses pole geometry).")
            # Draw a translucent magenta marker outlining the fence
            # shape (post columns + section quads) onto a copy of
            # the scene. The reference is NOT pre-pasted here —
            # it goes to the model as a separate image; the marker
            # only tells the model WHERE the fence should appear.
            overlay_scene_bytes = _build_poles_overlay(
                scene_bytes,
                poles,
                section_height_norm=pole_section_height,
                pole_section_lengths=pole_section_lengths,
                post_width_norm=pole_post_width,
                alpha=overlay_alpha,
            )
            aux_bytes = overlay_scene_bytes
            aux_kind = "overlay"
            engine_scene_bytes = overlay_scene_bytes
        else:  # mode == "mask"
            aux_bytes = binary_mask_bytes
            aux_kind = "mask"
            engine_scene_bytes = scene_bytes

        template = system_prompt.strip() if system_prompt else default_system_prompt("mask")

        # Post-clip with dilated + Gaussian-feathered polygon.
        #
        # Why dilated + feathered, not hard binary:
        #   - Hard clip at the polygon edge produces visible seams
        #     when the model's edit slightly bleeds past the polygon
        #     (shadows, ground-line transitions). Looks like a sticker
        #     was pasted onto the scene.
        #   - Dilated mask + Gaussian feather lets shadows and
        #     ground-line transitions extend a few pixels past the
        #     polygon naturally, then smoothly blends back to the
        #     original. The seam is invisible.
        #   - Inside the dilated region the model's output wins;
        #     outside it the original scene wins; the transition
        #     band is a smooth alpha blend.
        #
        # On variant-B (lawn polygon, P1 back-wall test), this
        # eliminates the "phantom flower bed" / "sky tone shift" /
        # "lawn texture re-render" artifacts that gpt-image-2
        # otherwise scatters across the scene, while preserving its
        # excellent inside-polygon rendering.
        from PIL import ImageFilter

        def _maybe_post_clip(model_output: bytes) -> bytes:
            if not post_clip_to_mask:
                return model_output
            with Image.open(io.BytesIO(model_output)) as raw:
                edited = raw.convert("RGB")
            with Image.open(io.BytesIO(scene_bytes)) as raw_scene:
                scene_img = raw_scene.convert("RGB")
            if edited.size != scene_img.size:
                edited = edited.resize(scene_img.size, Image.LANCZOS)
            W_, H_ = scene_img.size
            # Dilate by ~2% of the smaller scene dim — enough for
            # shadow extensions to feel natural, small enough to
            # still feel "inside the polygon" to the user.
            dilate = max(4, min(W_, H_) // 50)
            poly_mask = Image.new("L", (W_, H_), 0)
            ImageDraw.Draw(poly_mask).polygon(
                _polygon_to_pixels(mask_polygon, W_, H_), fill=255
            )
            poly_mask = poly_mask.filter(ImageFilter.MaxFilter(2 * dilate + 1))
            poly_mask = poly_mask.filter(ImageFilter.GaussianBlur(radius=dilate))
            blended = Image.composite(edited, scene_img, poly_mask)
            buf = io.BytesIO()
            blended.save(buf, format="PNG")
            return buf.getvalue()

        if mask_engine == "gpt_image_2":
            # OpenAI's gpt-image-2 (released April 21, 2026) hosted on
            # fal at openai/gpt-image-2/edit. The mask field is the
            # binary pole/polygon mask; the scene field is the
            # original scene (mask mode) or the pre-pasted overlay
            # (overlay mode) — gpt-image-2 sees the warped fence
            # already positioned and re-renders cleanly.
            fal = falai or FalAI()
            edit_resp = await fal.gpt_image_2.edit(
                scene=(engine_scene_bytes, scene_mime if engine_scene_bytes is scene_bytes else "image/png"),
                mask=(binary_mask_bytes, "image/png"),
                references=[(reference_bytes, reference_mime)],
                prompt=f"{instruction}. {template}",
                quality=gpt_image_2_quality,
                image_size="auto",
            )
            raw_bytes = _maybe_post_clip(edit_resp.image_bytes)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "gemini_translucent":
            # New empirical winner from the May 2026 wide sweep
            # (docs/results/26-translucent-*). Pre-paste the reference
            # into the polygon at 55% alpha — visible enough to give
            # Gemini a strong spatial cue, faded enough that the
            # model re-renders rather than copy-pastes. Single image
            # carries marker + identity + scene context together.
            prepasted_bytes = _build_translucent_prepaste(
                scene_bytes,
                reference_bytes,
                mask_polygon,
                alpha=translucent_alpha,
                reference_crop=reference_crop,
            )
            fal = falai or FalAI()
            simple_prompt = (
                f"{instruction}. Place the object from image 2 into the "
                "highlighted region in image 1. Re-render it cleanly so the "
                "transparency disappears; match the scene's perspective and "
                "lighting; preserve everything else in the scene."
            )
            edit_resp = await fal.nano_banana.edit(
                scene=(prepasted_bytes, "image/png"),
                references=[(reference_bytes, reference_mime)],
                prompt=simple_prompt,
                model=translucent_model,
            )
            raw_bytes = _maybe_post_clip(edit_resp.image_bytes)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "flux_ref_inpaint":
            # The single hosted endpoint that takes scene + mask +
            # reference + prompt as four native input fields. FLUX
            # treats the mask as a hard alpha constraint at the
            # provider level (no semantic-prior trap), and
            # reference_image_url conditions the inpainted region
            # toward the reference object's appearance. Empirically
            # the cleanest mask compliance of any engine in the
            # codebase (~0% strong outside-mask drift on variant-B).
            #
            # FLUX inpainting wants SHORT focused prompts — the long
            # PRESERVATION-CRITICAL template that gpt-image-1 needs
            # actively hurts FLUX's rendering. We pass just the
            # user's instruction here, with a minimal photorealistic
            # suffix. The reference_image_url does the heavy lifting
            # for identity, not the prompt.
            fal = falai or FalAI()
            flux_prompt = (
                f"{instruction}, photorealistic, matching the scene's "
                "perspective and lighting"
            )
            edit_resp = await fal.flux_ref_inpaint.edit(
                scene=(engine_scene_bytes, scene_mime if engine_scene_bytes is scene_bytes else "image/png"),
                mask=(binary_mask_bytes, "image/png"),
                reference=(reference_bytes, reference_mime),
                prompt=flux_prompt,
                reference_strength=flux_ref_strength,
                num_inference_steps=flux_ref_steps,
                guidance_scale=flux_ref_guidance,
            )
            raw_bytes = _maybe_post_clip(edit_resp.image_bytes)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "gemini_crop":
            # Crop+edit+reassemble. Bypasses the semantic-prior trap:
            # the model only sees a region around the polygon, not
            # other places in the scene where the object class
            # naturally lives, so it can't relocate. Empirically this
            # is the fastest (~30s) AND highest-fidelity engine —
            # see docs/results/21-* for the sweep that established it.
            crop_bytes, crop_box = _crop_with_marker(
                scene_bytes, mask_polygon, pad_frac=gemini_crop_pad_frac
            )
            fal = falai or FalAI()
            simple_prompt = (
                f"{instruction}. Place the object from image 2 inside the "
                "magenta marker region in image 1. Match the scene's "
                "perspective and lighting; the marker disappears in the "
                "output."
            )
            edit_resp = await fal.nano_banana.edit(
                scene=(crop_bytes, "image/png"),
                references=[(reference_bytes, reference_mime)],
                prompt=simple_prompt,
                model=gemini_crop_model,
            )
            reassembled = _reassemble_crop(
                scene_bytes, edit_resp.image_bytes, crop_box
            )
            raw_bytes = _maybe_post_clip(reassembled)
            raw_mime = "image/png"
            edit_text = ""

        elif mask_engine == "anydoor_chain":
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
                scene=(engine_scene_bytes, scene_mime if engine_scene_bytes is scene_bytes else "image/png"),
                scene_mask=(binary_mask_bytes, "image/png"),
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
                mask=(binary_mask_bytes, "image/png"),
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
                scene=(engine_scene_bytes, scene_mime if engine_scene_bytes is scene_bytes else "image/png"),
                mask=(binary_mask_bytes, "image/png"),
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
            mask_bytes = binary_mask_bytes  # white-on-black scene mask

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
                scene=(engine_scene_bytes, scene_mime if engine_scene_bytes is scene_bytes else "image/png"),
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
                scene=(engine_scene_bytes, scene_mime if engine_scene_bytes is scene_bytes else "image/png"),
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
        aux_bytes=aux_bytes if aux_kind in ("mask", "overlay") else b"",
        aux_kind=aux_kind if aux_kind in ("mask", "overlay") else None,
        masks=masks,
        text=edit_text,
    )
