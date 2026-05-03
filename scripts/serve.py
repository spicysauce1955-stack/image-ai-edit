"""Launch the local web server.

Usage::

    python scripts/serve.py            # listens on http://127.0.0.1:8000
    python scripts/serve.py --port 8080 --host 0.0.0.0

Requires the ``server`` extras::

    uv pip install -p .venv/bin/python -e .[server]

Open http://127.0.0.1:8000 to use the upload UI; POST multipart to
``/api/insert`` for programmatic access.
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the image-ai-edit server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on code changes (dev only).",
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "ai_edit.server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
