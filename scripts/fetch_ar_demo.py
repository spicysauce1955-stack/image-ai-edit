"""Download a known-good GLB into out/scenes/<scene-id>/ for manual AR smoke.

Phase 1 of the AR plan is a delivery-only feature: routes serve assets
that something else put on disk. This script is the "something else"
for manual phone testing — drops the Khronos Box sample (~3 KB) into a
scene directory so you can hit ``http://<server>/ar/<scene-id>`` from
a phone and verify the model-viewer + native AR handoff works.

USDZ is intentionally not fetched here — there's no canonical
public-domain stable URL for one, and Phase 2 will introduce on-the-fly
GLB→USDZ conversion. Until then, iOS Quick Look needs you to drop your
own ``.usdz`` next to ``model.glb`` if you want the iOS hand-off path
to work.

Usage::

    .venv/bin/python scripts/fetch_ar_demo.py             # → out/scenes/demo
    .venv/bin/python scripts/fetch_ar_demo.py --scene-id box1
    .venv/bin/python scripts/fetch_ar_demo.py --root /tmp/scenes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

# Khronos glTF-Sample-Assets / Box / Binary — the smallest non-trivial
# certified sample. Stable URL: this repo is the official Khronos
# replacement for the older glTF-Sample-Models, and "Box" has been
# present since the v2.0 launch.
BOX_GLB_URL = (
    "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/"
    "main/Models/Box/glTF-Binary/Box.glb"
)


def download_demo(root: Path, scene_id: str) -> Path:
    """Fetch the demo GLB into ``<root>/<scene_id>/model.glb``.

    Returns the on-disk path. Raises on HTTP error or network failure
    — callers should let the exception propagate so the CLI exits
    non-zero.
    """
    target_dir = root / scene_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "model.glb"

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(BOX_GLB_URL)
        resp.raise_for_status()
        target.write_bytes(resp.content)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--scene-id",
        default="demo",
        help="Scene identifier (used in the URL: /ar/<scene-id>). Default: 'demo'.",
    )
    parser.add_argument(
        "--root",
        default=str(Path.cwd() / "out" / "scenes"),
        help="Root directory for the AR store. Default: ./out/scenes",
    )
    args = parser.parse_args(argv)

    try:
        glb_path = download_demo(Path(args.root), args.scene_id)
    except httpx.HTTPError as exc:
        print(f"error: failed to download {BOX_GLB_URL}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {glb_path}")
    print()
    print("Next:")
    print(f"  1. Start the server:   .venv/bin/python scripts/serve.py")
    print(f"  2. From your phone:    http://<server-ip>:8000/ar/{args.scene_id}")
    print(f"  3. Tap 'View in your space' for AR.")
    print()
    print(
        "Note: Quick Look (iOS) needs a USDZ at "
        f"{Path(args.root) / args.scene_id / 'model.usdz'} — Phase 2 will add "
        "automatic conversion. For now Android Scene Viewer + the 3D preview "
        "still work."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
