"""One-off demo: fence.jpg → isolated multi-view → Hunyuan3D GLB.

Exercises FalAIMultiImageTo3D end-to-end on a real image. Staged so each
paid fal call can be inspected before spending on the next:

    isolate : fence.jpg → out/scenes/fence_demo/views/front.png  (one panel, plain bg)
    angles  : front.png → back.png / left.png / right.png
    model   : the views → out/scenes/fence_demo/model.glb (Hunyuan3D 3.1)
    all     : run every stage

Uses nano-banana-pro (Gemini 3 Pro Image via fal) for the image prep and
the FalAIMultiImageTo3D provider for the 3D step.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ai_edit.config import load_env
from ai_edit.models import MIME_GLB
from ai_edit.pipeline.asset_validate import validate_glb
from ai_edit.providers.falai import FalAI

ROOT = Path("out/scenes/fence_demo")
VIEWS = ROOT / "views"
SRC = Path("fence.jpg")

ISOLATE_PROMPT = (
    "Extract a SINGLE vertical fence panel section (the span between two "
    "posts) from this photo. Output only that one grey vinyl privacy fence "
    "panel together with its two end posts, viewed straight-on from the "
    "front, centered, on a plain pure-white seamless background. Remove all "
    "grass, plants, flowers, mulch, stone edging, trees, house and sky. "
    "Clean studio product photo, soft even lighting, no cast shadows, no "
    "ground plane."
)


def angle_prompt(view: str) -> str:
    return (
        "The image is a single grey vinyl fence panel section (one panel with "
        "two posts) isolated on a white background. Render the SAME fence "
        f"panel from {view}, keeping identical materials, colour, slat texture "
        "and proportions. Clean studio product photo on a plain pure-white "
        "seamless background, soft even lighting, centered, no cast shadows."
    )


BACK_PROMPT = angle_prompt("the back (rear face)")

# Single side view. We generate ONE side then mirror it for the other —
# a fence panel is left/right symmetric, so generating both independently
# just produces mismatched geometry (e.g. a stray mid-panel slat on one
# side only). Mirroring guarantees identical sides AND saves a paid call.
SIDE_PROMPT = (
    "The image is a single grey vinyl fence panel section isolated on white. "
    "Render the SAME panel viewed exactly edge-on from one side: a thin, "
    "uniform vertical profile showing the slim thickness of the panel and a "
    "single square end post with its flat cap. Straight clean edge — NO "
    "mid-panel protrusions, rails, or extra features. Plain pure-white "
    "seamless background, soft even lighting, centered, no cast shadows."
)


async def isolate(fal: FalAI) -> None:
    VIEWS.mkdir(parents=True, exist_ok=True)
    scene = (SRC.read_bytes(), "image/jpeg")
    resp = await fal.nano_banana.edit(scene, [], ISOLATE_PROMPT)
    out = VIEWS / "front.png"
    out.write_bytes(resp.image_bytes)
    print(f"wrote {out} ({len(resp.image_bytes)} bytes)")


async def angles(fal: FalAI) -> None:
    from io import BytesIO

    from PIL import Image

    front = (VIEWS / "front.png").read_bytes()

    # Back face (real generation).
    resp = await fal.nano_banana.edit((front, "image/png"), [], BACK_PROMPT)
    (VIEWS / "back.png").write_bytes(resp.image_bytes)
    print(f"wrote {VIEWS / 'back.png'} ({len(resp.image_bytes)} bytes)")

    # One side (real generation).
    resp = await fal.nano_banana.edit((front, "image/png"), [], SIDE_PROMPT)
    (VIEWS / "left.png").write_bytes(resp.image_bytes)
    print(f"wrote {VIEWS / 'left.png'} ({len(resp.image_bytes)} bytes)")

    # Other side = horizontal mirror of the first — assume symmetry so
    # the two sides are identical (avoids the asymmetric-slat artifact).
    mirrored = Image.open(BytesIO(resp.image_bytes)).transpose(Image.FLIP_LEFT_RIGHT)
    mirrored.save(VIEWS / "right.png")
    print(f"wrote {VIEWS / 'right.png'} (mirror of left — symmetry assumed)")


async def model(fal: FalAI, *, only: list[str] | None = None) -> None:
    order = only or ["front", "back", "left", "right"]
    refs: list[tuple[bytes, str]] = []
    for stem in order:
        p = VIEWS / f"{stem}.png"
        if p.is_file():
            refs.append((p.read_bytes(), "image/png"))
    if not refs:
        raise SystemExit("no view images found — run the isolate/angles stages first")
    print(f"generating 3D from {len(refs)} view(s): {order[:len(refs)]} (PBR on)…")
    resp = await fal.multi_image_3d.generate(
        "grey vinyl privacy fence panel section",
        references=refs,
        enable_pbr=True,
    )
    asset = resp.find(MIME_GLB)
    assert asset is not None, f"no GLB in response: {resp.raw}"
    validate_glb(asset.data)
    out = ROOT / "model.glb"
    out.write_bytes(asset.data)
    print(f"wrote {out} ({len(asset.data):,} bytes) — validated GLB")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("stage", choices=["isolate", "angles", "model", "all"])
    ap.add_argument(
        "--only",
        nargs="*",
        help="For the model stage: restrict to these view stems (e.g. front back).",
    )
    args = ap.parse_args()
    load_env()
    fal = FalAI()
    if args.stage in ("isolate", "all"):
        await isolate(fal)
    if args.stage in ("angles", "all"):
        await angles(fal)
    if args.stage in ("model", "all"):
        await model(fal, only=args.only)


if __name__ == "__main__":
    asyncio.run(main())
