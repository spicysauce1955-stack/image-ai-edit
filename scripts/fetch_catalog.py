"""Download curated catalog entries into the AR store.

Replaces / generalizes ``scripts/fetch_ar_demo.py``. Drop catalog
entries onto disk so the AR routes (``/ar/<id>``) can serve them.

Usage::

    .venv/bin/python scripts/fetch_catalog.py --all
    .venv/bin/python scripts/fetch_catalog.py --id box --id duck
    .venv/bin/python scripts/fetch_catalog.py --all --root /tmp/scenes
    .venv/bin/python scripts/fetch_catalog.py --catalog path/to/manifest.json --all

Exit code is non-zero if any selected entry produced an error
(missing URLs are not errors — they're tracked as "skipped").
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_edit.pipeline.asset_catalog import AssetCatalog, default_path
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.pipeline.catalog_fetch import fetch_all, format_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sel = parser.add_mutually_exclusive_group(required=True)
    sel.add_argument(
        "--all",
        action="store_true",
        help="Fetch every entry in the catalog.",
    )
    sel.add_argument(
        "--id",
        dest="ids",
        action="append",
        help="Fetch a specific entry by id. May be passed multiple times.",
    )
    parser.add_argument(
        "--catalog",
        default=None,
        help=f"Path to the catalog manifest. Default: {default_path()}",
    )
    parser.add_argument(
        "--root",
        default=str(Path.cwd() / "out" / "scenes"),
        help="Root directory for the AR store. Default: ./out/scenes",
    )
    args = parser.parse_args(argv)

    try:
        catalog = AssetCatalog.load(args.catalog)
    except (OSError, ValueError) as exc:
        print(f"error: failed to load catalog: {exc}", file=sys.stderr)
        return 2

    store = FilesystemARStore(args.root)
    ids = None if args.all else args.ids

    try:
        results = fetch_all(catalog, store, ids=ids)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(format_summary(results))

    failed = [r.asset_id for r in results if r.any_error]
    no_success = [r.asset_id for r in results if not r.any_success]

    if failed:
        print(file=sys.stderr)
        print(
            f"error: {len(failed)} entr{'y' if len(failed) == 1 else 'ies'} "
            f"had download failures: {', '.join(failed)}",
            file=sys.stderr,
        )
        return 1
    if no_success:
        # Reach this branch only if a selected entry had neither URL
        # set — surfacing it is friendlier than silently doing nothing.
        print(file=sys.stderr)
        print(
            f"warning: {len(no_success)} entr{'y' if len(no_success) == 1 else 'ies'} "
            f"had no fetchable URLs: {', '.join(no_success)}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
