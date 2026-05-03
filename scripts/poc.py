"""POC CLI: insert a reference object into a scene photo.

Usage:
    python scripts/poc.py SCENE.jpg REFERENCE.jpg "instruction text"

Optional:
    --segment "ground,trees,sky"   request Grounded-SAM masks for these labels
    --out DIR                      output dir (default: out/)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from ai_edit import load_env
from ai_edit.pipeline import insert_object


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Insert a reference object into a scene.")
    p.add_argument("scene", type=Path, help="Scene image (e.g. backyard.jpg)")
    p.add_argument("reference", type=Path, help="Reference object image (e.g. fence.jpg)")
    p.add_argument("instruction", help="What to do, e.g. 'put this fence along the back of the yard'")
    p.add_argument(
        "--segment",
        default="",
        help="Comma-separated labels to mask via Grounded-SAM (e.g. 'ground,trees,sky'). "
        "Empty = skip segmentation.",
    )
    p.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    return p.parse_args()


async def main() -> int:
    load_env()
    args = parse_args()

    if not args.scene.exists():
        print(f"error: scene not found: {args.scene}", file=sys.stderr)
        return 2
    if not args.reference.exists():
        print(f"error: reference not found: {args.reference}", file=sys.stderr)
        return 2

    seg_prompts = [s.strip() for s in args.segment.split(",") if s.strip()]

    args.out.mkdir(parents=True, exist_ok=True)
    masks_dir = args.out / "masks"
    composites_dir = args.out / "composites"
    masks_dir.mkdir(exist_ok=True)
    composites_dir.mkdir(exist_ok=True)

    print(f"[poc] scene={args.scene} reference={args.reference}")
    if seg_prompts:
        print(f"[poc] segmenting: {seg_prompts}")

    t0 = time.time()
    result = await insert_object(
        args.scene,
        args.reference,
        args.instruction,
        segmentation_prompts=seg_prompts or None,
    )
    elapsed = time.time() - t0

    ts = time.strftime("%Y%m%d-%H%M%S")
    for mask in result.masks:
        out = masks_dir / f"{ts}-{mask.label.replace(' ', '_')}.png"
        out.write_bytes(mask.image_bytes)
        print(f"[poc] mask  -> {out}")

    ext = "png" if result.composite_mime == "image/png" else "jpg"
    composite_path = composites_dir / f"{ts}.{ext}"
    composite_path.write_bytes(result.composite_bytes)
    print(f"[poc] composite -> {composite_path}  ({elapsed:.1f}s)")
    if result.text:
        print(f"[poc] model text: {result.text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
