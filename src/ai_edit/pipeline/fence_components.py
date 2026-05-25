"""Build reusable PANEL + POST fence components from a source image.

Phase 8.B. Produces the two GLB components the layout engine
(`pipeline/fence.py`) assembles: a **panel-only** GLB (the infill,
posts removed) and a **post-only** GLB. Each is stored in an `ARStore`
and returned as a `ComponentRef` with its measured nominal width.

Reuses, does not modify:
- `FalAINanoBanana` (isolate + multi-view angle generation),
- `FalAIMultiImageTo3D` (image→3D),
- `scripts/optimize_glb.py` (delivery-weight pass, via subprocess),
- `ARStore`, `validate_glb`.

Symmetry: for the panel we generate front + back + one side and mirror
it (a panel is left/right symmetric — saves a call and keeps the sides
consistent); the post is a simple symmetric column, so a single front
view is enough.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from ..models.base import MIME_GLB, Scene3DAsset
from .ar_store import ARStore
from .asset_validate import validate_glb
from .fence import ComponentRef

_OPTIMIZE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "optimize_glb.py"

PANEL_ISOLATE_PROMPT = (
    "Extract ONLY the flat fence panel infill between the posts — the "
    "rectangular grey vinyl panel (vertical slats with top and bottom "
    "rails) WITHOUT the end posts. Remove both posts entirely. Show the "
    "panel straight-on from the front, centered, on a plain pure-white "
    "seamless background. No grass, plants, ground, or sky. Clean studio "
    "product photo, soft even lighting, no cast shadows."
)
POST_ISOLATE_PROMPT = (
    "Extract ONLY a SINGLE fence post — one vertical grey vinyl post with "
    "its flat top cap, no panel and no rails attached. Show it straight-on "
    "from the front, centered, on a plain pure-white seamless background. "
    "No panel, no background. Clean studio product photo, soft even "
    "lighting, no cast shadows."
)
_BACK_PROMPT = (
    "The image is a single grey vinyl fence panel infill (no posts) on "
    "white. Render the SAME panel from the back (rear face), identical "
    "materials/colour/proportions, plain pure-white background, soft even "
    "lighting, centered, no cast shadows."
)
_SIDE_PROMPT = (
    "The image is a single grey vinyl fence panel infill on white. Render "
    "the SAME panel viewed exactly edge-on from one side: a thin uniform "
    "vertical profile, no protrusions, plain pure-white background, soft "
    "even lighting, centered, no cast shadows."
)


@dataclass(frozen=True)
class FenceComponents:
    panel: ComponentRef
    post: ComponentRef


def panel_component_id(base_id: str) -> str:
    return f"{base_id}__panel"


def post_component_id(base_id: str) -> str:
    return f"{base_id}__post"


def measure_nominal_width(glb_bytes: bytes) -> float:
    """Return the model's width = X-extent (metres/model-units).

    Assumes the component is upright with +X = width (what
    `optimize_glb` produces). Loaded via trimesh.
    """
    import trimesh

    scene = trimesh.load(BytesIO(glb_bytes), file_type="glb", force="scene")
    mesh = scene.to_geometry() if hasattr(scene, "to_geometry") else scene.dump(concatenate=True)
    return float(mesh.extents[0])


def _optimize(glb_bytes: bytes, *, faces: int, texture_size: int) -> bytes:
    """Run the existing optimize_glb.py over the bytes via subprocess."""
    with tempfile.TemporaryDirectory(prefix="fence-comp-") as tmp:
        src = Path(tmp) / "in.glb"
        dst = Path(tmp) / "out.glb"
        src.write_bytes(glb_bytes)
        subprocess.run(
            [
                sys.executable, str(_OPTIMIZE_SCRIPT),
                str(src), str(dst),
                "--faces", str(faces), "--texture-size", str(texture_size),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return dst.read_bytes()


async def _make_views(
    fal, front_png: bytes, *, multiview: bool
) -> list[tuple[bytes, str]]:
    """Front view → ordered view list for Hunyuan3D's named slots.

    Order matches FalAIMultiImageTo3D: front(input), back, left, right.
    Right is the horizontal mirror of left (symmetry).
    """
    if not multiview:
        return [(front_png, "image/png")]

    from PIL import Image

    back = (await fal.nano_banana.edit((front_png, "image/png"), [], _BACK_PROMPT)).image_bytes
    left = (await fal.nano_banana.edit((front_png, "image/png"), [], _SIDE_PROMPT)).image_bytes
    right = BytesIO()
    Image.open(BytesIO(left)).transpose(Image.FLIP_LEFT_RIGHT).save(right, format="PNG")
    return [
        (front_png, "image/png"),
        (back, "image/png"),
        (left, "image/png"),
        (right.getvalue(), "image/png"),
    ]


async def build_component(
    *,
    fal,
    store: ARStore,
    source_image: tuple[bytes, str],
    component_id: str,
    isolate_prompt: str,
    multiview: bool,
    optimize: bool = True,
    faces: int = 40000,
    texture_size: int = 2048,
) -> ComponentRef:
    """Isolate → (multi-view) → image→3D → optimize → store → ComponentRef."""
    front = (await fal.nano_banana.edit(source_image, [], isolate_prompt)).image_bytes
    views = await _make_views(fal, front, multiview=multiview)
    resp = await fal.multi_image_3d.generate(component_id, references=views, enable_pbr=True)
    asset = resp.find(MIME_GLB)
    if asset is None:
        raise RuntimeError(f"no GLB returned for {component_id!r}: {resp.raw}")

    glb = asset.data
    if optimize:
        glb = _optimize(glb, faces=faces, texture_size=texture_size)
    validate_glb(glb)

    width = measure_nominal_width(glb)
    store.put(component_id, Scene3DAsset(data=glb, mime_type=MIME_GLB, extension=".glb"))
    return ComponentRef(asset_id=component_id, nominal_width=width)


async def build_fence_components(
    *,
    fal,
    store: ARStore,
    source_image: tuple[bytes, str],
    base_id: str,
    optimize: bool = True,
) -> FenceComponents:
    """Build both the panel (multi-view) and post (single-view) components."""
    panel = await build_component(
        fal=fal,
        store=store,
        source_image=source_image,
        component_id=panel_component_id(base_id),
        isolate_prompt=PANEL_ISOLATE_PROMPT,
        multiview=True,
        optimize=optimize,
    )
    post = await build_component(
        fal=fal,
        store=store,
        source_image=source_image,
        component_id=post_component_id(base_id),
        isolate_prompt=POST_ISOLATE_PROMPT,
        multiview=False,
        optimize=optimize,
    )
    return FenceComponents(panel=panel, post=post)
