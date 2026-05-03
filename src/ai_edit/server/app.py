"""FastAPI app wrapping :func:`ai_edit.pipeline.insert.insert_object`.

Endpoints
---------
``GET /``
    Static HTML page with a drag-drop upload form. Calls ``/api/insert``
    via ``fetch`` and renders the resulting composite inline.

``POST /api/insert``
    Multipart upload: ``scene`` (file), ``reference`` (file),
    ``instruction`` (str), optional ``segment`` (comma-separated labels)
    and ``relight`` (relight prompt). Returns the composite as a PNG
    binary response.

``GET /healthz``
    Liveness probe.

The app is intentionally stateless: nothing is written to disk on the
server side. Composites are returned in the response body so the caller
decides what to do with them.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

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
    ) -> Response:
        """Run the insertion pipeline on uploaded images.

        Streams the resulting composite back as a single PNG. Errors
        from the pipeline (timeouts, model refusals, missing keys) are
        surfaced as HTTP 502 with the exception message in the body so
        the caller can show something useful to the user.
        """
        scene_bytes = await scene.read()
        reference_bytes = await reference.read()

        # Persist the uploads to a temp directory only because
        # insert_object takes paths today. A future refactor could let
        # it accept bytes directly to skip this round-trip; for now
        # this keeps the server stateless from the caller's POV
        # (everything lives under /tmp and is never re-read).
        import tempfile

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
                    segmentation_prompts=seg_prompts or None,
                    relight_prompt=relight_prompt,
                )
            except Exception as exc:
                # Surface upstream failures as 502 — the API itself is
                # fine, but its dependency failed.
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        return Response(
            content=result.composite_bytes,
            media_type=result.composite_mime,
            headers={"Cache-Control": "no-store"},
        )

    return app


# Convenience for `uvicorn ai_edit.server.app:app`.
app = create_app()
