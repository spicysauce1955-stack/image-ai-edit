"""HTTP API + minimal upload UI around the insertion pipeline.

Importing this subpackage requires the ``server`` extras
(``uv pip install -p .venv/bin/python -e .[server]``). It is kept
optional so the core ``ai_edit`` package stays free of FastAPI/uvicorn
dependencies for callers that only want the providers.
"""

from .app import create_app

__all__ = ["create_app"]
