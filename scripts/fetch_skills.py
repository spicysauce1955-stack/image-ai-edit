"""Install the three.js Agent Skills subset into .claude/skills/.

These skills (from CloudAI-X/threejs-skills) give Claude Code working
knowledge of the three.js APIs the AR live page (`/ar/<id>/live`)
relies on — scene/camera/renderer setup, GLTF loading,
interaction/raycasting, and lighting. They're instruction-only
Markdown (no executable scripts).

Why fetch instead of commit the files: the upstream repo ships no
license, so vendoring a copy into this repo would be redistributing
unlicensed content. This script makes the install reproducible
without committing the skill bodies — same spirit as
``fetch_catalog.py`` (we version-control the *source*, not the
fetched artifact). ``.claude/skills/`` is gitignored.

Usage::

    .venv/bin/python scripts/fetch_skills.py            # default subset
    .venv/bin/python scripts/fetch_skills.py --all      # all upstream modules
    .venv/bin/python scripts/fetch_skills.py --list     # show what's available
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://github.com/CloudAI-X/threejs-skills"

# The modules that map to code paths in src/ai_edit/server/ar_routes.py
# (the /ar/<id>/live three.js page) and the upcoming Phase 6.C work.
DEFAULT_SUBSET = [
    "threejs-fundamentals",   # scene / camera / renderer / animation loop
    "threejs-loaders",        # GLTFLoader — we load catalog GLBs
    "threejs-interaction",    # raycasting / controls — Phase 6.C gestures
    "threejs-lighting",       # Hemisphere + Directional lights on the live page
]

DEFAULT_DEST = Path(".claude/skills")


def _clone(dest: Path) -> Path:
    """Shallow-clone the upstream repo into ``dest``; return its skills dir."""
    subprocess.run(
        ["git", "clone", "--depth", "1", REPO, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest / "skills"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--all",
        action="store_true",
        help="Install every module the upstream repo ships, not just the subset.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the modules available upstream and exit (no install).",
    )
    parser.add_argument(
        "--dest",
        default=str(DEFAULT_DEST),
        help=f"Where to install the skills (default: {DEFAULT_DEST}).",
    )
    args = parser.parse_args(argv)

    if not shutil.which("git"):
        print("error: git is required to fetch skills.", file=sys.stderr)
        return 127

    with tempfile.TemporaryDirectory(prefix="threejs-skills-") as tmp:
        try:
            skills_src = _clone(Path(tmp))
        except subprocess.CalledProcessError as exc:
            print(f"error: clone failed: {exc.stderr or exc}", file=sys.stderr)
            return 1

        available = sorted(p.name for p in skills_src.iterdir() if p.is_dir())

        if args.list:
            print(f"Available modules in {REPO}:")
            for name in available:
                marker = "*" if name in DEFAULT_SUBSET else " "
                print(f"  [{marker}] {name}")
            print("\n(* = installed by default; pass --all for everything)")
            return 0

        wanted = available if args.all else DEFAULT_SUBSET
        dest = Path(args.dest)
        dest.mkdir(parents=True, exist_ok=True)

        installed: list[str] = []
        for name in wanted:
            src = skills_src / name
            if not src.is_dir():
                print(f"warning: {name!r} not found upstream; skipping.", file=sys.stderr)
                continue
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
            installed.append(name)

    if not installed:
        print("error: nothing installed.", file=sys.stderr)
        return 1

    print(f"installed {len(installed)} skill(s) into {dest}/:")
    for name in installed:
        print(f"  {name}")
    print()
    print("Restart Claude Code (or reload skills) to pick them up.")
    print("Source: " + REPO + " (instruction-only; no license — not vendored into git)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
