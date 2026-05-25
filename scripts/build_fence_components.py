"""Build PANEL + POST fence components from an image (Phase 8.B).

Produces two GLB components in the AR store — `<base>__panel` (multi-view)
and `<base>__post` (single view) — and prints their ids, measured nominal
widths, and AR URLs. Real fal generations (costs apply).

Usage::

    .venv/bin/python scripts/build_fence_components.py fence.jpg --base fence
    .venv/bin/python scripts/build_fence_components.py fence.jpg --base fence --no-optimize
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ai_edit.config import load_env
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.pipeline.fence_components import build_fence_components
from ai_edit.providers.falai import FalAI

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


async def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("image")
    ap.add_argument("--base", required=True, help="Base id; components are <base>__panel / <base>__post.")
    ap.add_argument("--root", default="out/scenes", help="AR store root (default out/scenes).")
    ap.add_argument("--no-optimize", action="store_true", help="Skip the delivery-weight pass.")
    args = ap.parse_args(argv)

    load_env()
    img_path = Path(args.image)
    mime = _MIME.get(img_path.suffix.lower(), "image/jpeg")
    source = (img_path.read_bytes(), mime)

    fal = FalAI()
    store = FilesystemARStore(args.root)

    print(f"building fence components from {args.image} (base={args.base})…")
    comps = await build_fence_components(
        fal=fal,
        store=store,
        source_image=source,
        base_id=args.base,
        optimize=not args.no_optimize,
    )
    print()
    for label, ref in (("panel", comps.panel), ("post", comps.post)):
        print(f"  {label}: {ref.asset_id}  width={ref.nominal_width:.3f}  → /ar/{ref.asset_id}")
    print()
    print("View: start the server, open /ar/<id> for each component.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
