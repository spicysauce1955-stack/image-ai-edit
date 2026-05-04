"""FastAPI app wrapping the insertion pipeline.

Endpoints
---------
``GET /``
    Drag-drop UI for the insertion pipeline. Calls ``/api/insert`` and
    renders the composite inline. Supports a refinement loop
    (multi-turn editing) and an attempt history.

``POST /api/insert``
    Multipart upload for one composite generation. Optional ``previous``
    field flips it into refinement mode. Returns the composite as a PNG
    binary response.

``GET /healthz``
    Liveness probe.

State
-----
The app is fully stateless. Uploads land in a
``tempfile.TemporaryDirectory`` and are deleted before the response is
sent; composites are streamed straight back in the response body.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ..config import load_env
from ..pipeline import insert_object

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Build and return the FastAPI app.

    Loads ``.env`` once at startup so providers can find their keys
    when constructed lazily inside :func:`insert_object`.
    """
    load_env()
    app = FastAPI(title="image-ai-edit", version="0.1.0")

    # Serve /static/* (CSS, JS, etc.) from the same directory that
    # holds index.html. Keeps the front-end zero-build: just static
    # files, no bundler.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/api/insert")
    async def insert(
        request: Request,
        scene: UploadFile = File(...),
        reference: UploadFile = File(...),
        instruction: str = Form(...),
        segment: str = Form(""),
        relight: str = Form(""),
        previous: UploadFile | None = File(None),
    ) -> Response:
        """Run the insertion pipeline on uploaded images.

        Streams the resulting composite back as a single PNG. Errors
        from the pipeline (timeouts, model refusals, missing keys) are
        surfaced as HTTP 502 with the exception message in the body so
        the caller can show something useful to the user.

        Multi-turn editing
        ------------------
        When ``previous`` is supplied (the bytes of an earlier composite
        from this conversation), the pipeline switches into refinement
        mode and Gemini edits the previous composite rather than
        starting from scratch — see :func:`insert_object` for details.
        """
        scene_bytes = await scene.read()
        reference_bytes = await reference.read()
        previous_bytes = await previous.read() if previous is not None else None
        previous_mime = (previous.content_type or "image/png") if previous else "image/png"

        # Persist uploads to a temp dir only because insert_object takes
        # paths today. A future refactor could let it accept bytes
        # directly to skip this round-trip.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scene_path = tmp_path / (scene.filename or "scene.bin")
            reference_path = tmp_path / (reference.filename or "reference.bin")
            scene_path.write_bytes(scene_bytes)
            reference_path.write_bytes(reference_bytes)

            seg_prompts = [s.strip() for s in segment.split(",") if s.strip()]
            relight_prompt = relight.strip() or None

            try:
                result = await insert_object(
                    scene_path,
                    reference_path,
                    instruction,
                    previous_composite=previous_bytes,
                    previous_mime=previous_mime,
                    segmentation_prompts=seg_prompts or None,
                    relight_prompt=relight_prompt,
                )
            except Exception as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        return Response(
            content=result.composite_bytes,
            media_type=result.composite_mime,
            headers={"Cache-Control": "no-store"},
        )

    return app


# Convenience for `uvicorn ai_edit.server.app:app`.
app = create_app()
