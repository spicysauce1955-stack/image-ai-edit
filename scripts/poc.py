"""POC CLI — insert a reference object into a scene photo.

Thin wrapper around :func:`ai_edit.pipeline.insert.insert_object` that
handles file I/O and writes results into ``out/``.

Usage
-----
::

    python scripts/poc.py SCENE.jpg REFERENCE.jpg "instruction text"

Optional flags
--------------
``--segment LABELS``
    Comma-separated labels (e.g. ``"ground,trees,sky"``) to mask via
    Grounded-SAM. Empty = skip segmentation, in which case
    ``REPLICATE_API_TOKEN`` is not needed.
``--relight PROMPT``
    Relight the Gemini composite via fal.ai IC-Light v2. Empty = skip
    relight, in which case ``FAL_KEY`` is not needed. When relight runs
    we save **both** the raw Gemini composite and the relit version
    side-by-side so the caller can A/B them.
``--out DIR``
    Where to write outputs (default: ``out/``). Composites land in
    ``DIR/composites/<timestamp>(-raw|-relit).<ext>``; per-label masks
    land in ``DIR/masks/<timestamp>-<label>.png``.

Exit codes
----------
``0``
    Success.
``2``
    A required input image was not found.
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
    """Parse CLI arguments for the POC."""
    p = argparse.ArgumentParser(description="Insert a reference object into a scene.")
    p.add_argument("scene", type=Path, help="Scene image (e.g. backyard.jpg)")
    p.add_argument(
        "reference", type=Path, help="Reference object image (e.g. fence.jpg)"
    )
    p.add_argument(
        "instruction",
        help="What to do, e.g. 'put this fence along the back of the yard'",
    )
    p.add_argument(
        "--segment",
        default="",
        help="Comma-separated labels to mask via Grounded-SAM (e.g. 'ground,trees,sky'). "
        "Empty = skip segmentation.",
    )
    p.add_argument(
        "--relight",
        default="",
        help="Relight the composite via fal.ai IC-Light with this prompt "
        "(e.g. 'warm afternoon sun from the right, soft ground shadows'). "
        "Empty = skip relight.",
    )
    p.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    return p.parse_args()


async def main() -> int:
    """Entry point used by ``if __name__ == '__main__'`` below."""
    # Load .env before anything else so providers find their keys when
    # they're constructed inside insert_object().
    load_env()
    args = parse_args()

    if not args.scene.exists():
        print(f"error: scene not found: {args.scene}", file=sys.stderr)
        return 2
    if not args.reference.exists():
        print(f"error: reference not found: {args.reference}", file=sys.stderr)
        return 2

    seg_prompts = [s.strip() for s in args.segment.split(",") if s.strip()]
    relight_prompt = args.relight.strip() or None

    args.out.mkdir(parents=True, exist_ok=True)
    masks_dir = args.out / "masks"
    composites_dir = args.out / "composites"
    masks_dir.mkdir(exist_ok=True)
    composites_dir.mkdir(exist_ok=True)

    print(f"[poc] scene={args.scene} reference={args.reference}")
    if seg_prompts:
        print(f"[poc] segmenting: {seg_prompts}")
    if relight_prompt:
        print(f"[poc] relighting: {relight_prompt!r}")

    t0 = time.time()
    result = await insert_object(
        args.scene,
        args.reference,
        args.instruction,
        segmentation_prompts=seg_prompts or None,
        relight_prompt=relight_prompt,
    )
    elapsed = time.time() - t0

    # Timestamp prefixes mean repeated runs accumulate side-by-side
    # rather than overwriting each other — important when iterating
    # on the prompt or vendor.
    ts = time.strftime("%Y%m%d-%H%M%S")
    for mask in result.masks:
        out = masks_dir / f"{ts}-{mask.label.replace(' ', '_')}.png"
        out.write_bytes(mask.image_bytes)
        print(f"[poc] mask  -> {out}")

    ext = "png" if result.composite_mime == "image/png" else "jpg"
    if result.composite_bytes_relit:
        # When relight ran, write both versions so the caller can A/B.
        raw_path = composites_dir / f"{ts}-raw.png"
        relit_path = composites_dir / f"{ts}-relit.{ext}"
        raw_path.write_bytes(result.composite_bytes_raw)
        relit_path.write_bytes(result.composite_bytes_relit)
        print(f"[poc] composite (raw)   -> {raw_path}")
        print(f"[poc] composite (relit) -> {relit_path}  ({elapsed:.1f}s)")
    else:
        composite_path = composites_dir / f"{ts}.{ext}"
        composite_path.write_bytes(result.composite_bytes)
        print(f"[poc] composite -> {composite_path}  ({elapsed:.1f}s)")

    if result.text:
        print(f"[poc] model text: {result.text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
