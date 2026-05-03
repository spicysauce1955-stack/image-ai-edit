"""FastAPI app wrapping the insertion + AR pipelines.

Endpoints
---------
``GET /``
    Drag-drop UI for the 2D insertion pipeline. Calls ``/api/insert``
    and renders the composite inline. Supports a refinement loop
    (multi-turn editing).

``POST /api/insert``
    Multipart upload for one composite generation. Optional ``previous``
    field flips it into refinement mode. Returns the composite as a PNG
    binary response.

``POST /api/build-ar``
    Multipart upload of N reference photos. Calls Meshy
    Multi-Image-to-3D, stashes the resulting GLB+USDZ in an in-memory
    store, and returns ``{"id": ..., "viewer_url": ...}``. Note: Meshy
    generations take **minutes**; this endpoint holds the connection
    open until the asset is ready.

``GET /ar/{id}``
    HTML page that loads the generated asset in ``<model-viewer>`` —
    Quick Look on iOS, Scene Viewer on Android, plain WebGL elsewhere.

``GET /ar/{id}/model.glb``
``GET /ar/{id}/model.usdz``
    Asset files served from the in-memory store.

``GET /healthz``
    Liveness probe.

State
-----
The 2D pipeline is fully stateless. The AR pipeline keeps an in-memory
``_AR_STORE`` keyed by UUID so the viewer page can fetch the bytes —
that's the minimum needed to serve a GLB/USDZ pair from the same
server. Bytes evict only on process restart; for a real deployment swap
the dict for an LRU cache or object storage.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from ..config import load_env
from ..pipeline import build_ar_asset, insert_object
from ..pipeline.ar import ARAsset

STATIC_DIR = Path(__file__).parent / "static"

# Module-level so it survives across requests on the same process.
# A real deployment should replace this with object storage (S3, R2)
# and serve assets from there directly.
_AR_STORE: dict[str, ARAsset] = {}


def create_app() -> FastAPI:
    """Build and return the FastAPI app.

    Loads ``.env`` once at startup so providers can find their keys
    when constructed lazily inside the pipelines.
    """
    load_env()
    app = FastAPI(title="image-ai-edit", version="0.1.0")

    # ------------------------------------------------------------------
    # Health + index
    # ------------------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    # ------------------------------------------------------------------
    # 2D insertion
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # AR / image-to-3D
    # ------------------------------------------------------------------

    @app.post("/api/build-ar")
    async def build_ar(
        request: Request,
        references: list[UploadFile] = File(...),
    ) -> dict[str, str]:
        """Generate a GLB + USDZ from N reference photos via Meshy.

        **Slow.** Meshy multi-image-to-3D typically takes 5–10 minutes.
        The connection is held open for the entire job; this is fine for
        localhost POC use but should become an async job + polling
        endpoint before exposing to real users.
        """
        if not references:
            raise HTTPException(status_code=400, detail="At least one reference required.")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ref_paths: list[Path] = []
            for i, up in enumerate(references):
                p = tmp_path / (up.filename or f"ref-{i}.bin")
                p.write_bytes(await up.read())
                ref_paths.append(p)

            try:
                asset = await build_ar_asset(ref_paths)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        ar_id = uuid.uuid4().hex[:12]
        _AR_STORE[ar_id] = asset

        base = str(request.base_url).rstrip("/")
        return {
            "id": ar_id,
            "viewer_url": f"{base}/ar/{ar_id}",
            "glb_url": f"{base}/ar/{ar_id}/model.glb",
            "usdz_url": f"{base}/ar/{ar_id}/model.usdz",
        }

    @app.get("/ar/{ar_id}")
    async def ar_view(ar_id: str) -> HTMLResponse:
        """Render the ``<model-viewer>`` page for a generated asset."""
        if ar_id not in _AR_STORE:
            raise HTTPException(status_code=404, detail="AR asset not found.")
        template = (STATIC_DIR / "ar.html").read_text()
        # Tiny templating — avoids pulling in jinja for two substitutions.
        rendered = template.replace("__AR_ID__", ar_id)
        return HTMLResponse(rendered)

    @app.get("/ar/{ar_id}/model.glb")
    async def ar_glb(ar_id: str) -> Response:
        asset = _AR_STORE.get(ar_id)
        if not asset:
            raise HTTPException(status_code=404, detail="AR asset not found.")
        if not asset.glb_bytes:
            raise HTTPException(status_code=404, detail="GLB unavailable for this asset.")
        return Response(content=asset.glb_bytes, media_type="model/gltf-binary")

    @app.get("/ar/{ar_id}/model.usdz")
    async def ar_usdz(ar_id: str) -> Response:
        asset = _AR_STORE.get(ar_id)
        if not asset:
            raise HTTPException(status_code=404, detail="AR asset not found.")
        if not asset.usdz_bytes:
            raise HTTPException(status_code=404, detail="USDZ unavailable for this asset.")
        return Response(content=asset.usdz_bytes, media_type="model/vnd.usdz+zip")

    return app


# Convenience for `uvicorn ai_edit.server.app:app`.
app = create_app()
