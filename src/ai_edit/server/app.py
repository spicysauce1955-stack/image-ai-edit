"""FastAPI app wrapping the insertion pipeline.

Endpoints
---------
``GET /``
    Drag-drop UI. Lets the user upload a scene + reference, draw a
    polygon region on the scene, and run the insertion pipeline.

``POST /api/insert``
    Multipart upload for one composite generation. Optional fields:
    ``polygon`` (JSON list of normalized [u, v] pairs), ``previous``
    (bytes of an earlier composite for refinement), ``segment``
    (Grounded-SAM labels), ``relight`` (IC-Light prompt).
    Returns a JSON envelope:
    ``{"composite_url": "...", "mask_url": "..." | null, "text": "..."}``.
    The actual image bytes are served from short-lived in-memory tokens.

``GET /api/result/{token}/composite.png``
``GET /api/result/{token}/mask.png``
    One-shot fetches for the result bytes referenced by the JSON above.
    Used so the client can show composite + mask side by side without
    re-uploading and without inflating the JSON with base64.

``GET /healthz``
    Liveness probe.

State
-----
The composite cache is a process-local dict keyed by an opaque token.
Entries evict on process restart; nothing is persisted to disk.
"""

from __future__ import annotations

import json
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ..config import load_env
from ..pipeline import insert_object

STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class _CachedResult:
    composite_bytes: bytes
    composite_mime: str
    mask_bytes: bytes  # empty if no polygon was drawn


# Module-level cache so tokens issued by /api/insert resolve in
# subsequent /api/result/<token>/* fetches. Capped to keep memory
# bounded under load — see _cache_put.
_RESULT_CACHE: dict[str, _CachedResult] = {}
_CACHE_CAP = 64


def _cache_put(result: _CachedResult) -> str:
    """Store a result and return an opaque token.

    Evicts the oldest entry when the cache is full. Tokens are
    cryptographically random so they aren't guessable by other clients.
    """
    if len(_RESULT_CACHE) >= _CACHE_CAP:
        # Pop oldest (insertion-ordered dict — Python 3.7+).
        _RESULT_CACHE.pop(next(iter(_RESULT_CACHE)))
    token = secrets.token_urlsafe(16)
    _RESULT_CACHE[token] = result
    return token


def _parse_polygon(raw: str) -> list[tuple[float, float]] | None:
    """Parse the ``polygon`` form field.

    Empty string → None (no polygon drawn). Otherwise expect a JSON
    list of ``[u, v]`` pairs with values in ``[0, 1]``. Anything else
    raises ``HTTPException(400)`` so the client gets a helpful message
    rather than a generic 502.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid polygon JSON: {exc}")
    if not isinstance(parsed, list) or len(parsed) < 3:
        raise HTTPException(
            status_code=400,
            detail="polygon must be a JSON list of at least 3 [u, v] pairs.",
        )
    points: list[tuple[float, float]] = []
    for p in parsed:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise HTTPException(
                status_code=400, detail=f"Bad polygon vertex: {p!r}"
            )
        u, v = float(p[0]), float(p[1])
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise HTTPException(
                status_code=400,
                detail=f"Polygon vertices must be normalized to [0, 1]: got {p!r}",
            )
        points.append((u, v))
    return points


def create_app() -> FastAPI:
    """Build and return the FastAPI app.

    Loads ``.env`` once at startup so providers can find their keys
    when constructed lazily inside :func:`insert_object`.
    """
    load_env()
    app = FastAPI(title="image-ai-edit", version="0.1.0")

    # Serve /static/* from the same directory as index.html. Zero-build
    # frontend; no bundler.
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
        polygon: str = Form(""),
        segment: str = Form(""),
        relight: str = Form(""),
        previous: UploadFile | None = File(None),
    ) -> dict[str, str | None]:
        """Run the insertion pipeline on uploaded images.

        Returns a JSON envelope with one-shot URLs for the composite
        and (if a polygon was provided) the rasterized mask. The bytes
        live in a short-lived in-memory cache keyed by random token.
        """
        scene_bytes = await scene.read()
        reference_bytes = await reference.read()
        previous_bytes = await previous.read() if previous is not None else None
        previous_mime = (previous.content_type or "image/png") if previous else "image/png"

        polygon_pts = _parse_polygon(polygon)
        seg_prompts = [s.strip() for s in segment.split(",") if s.strip()]
        relight_prompt = relight.strip() or None

        # Persist uploads to a temp dir only because insert_object takes
        # paths today. Cleared as soon as the response is built.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scene_path = tmp_path / (scene.filename or "scene.bin")
            reference_path = tmp_path / (reference.filename or "reference.bin")
            scene_path.write_bytes(scene_bytes)
            reference_path.write_bytes(reference_bytes)

            try:
                result = await insert_object(
                    scene_path,
                    reference_path,
                    instruction,
                    mask_polygon=polygon_pts,
                    previous_composite=previous_bytes,
                    previous_mime=previous_mime,
                    segmentation_prompts=seg_prompts or None,
                    relight_prompt=relight_prompt,
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        token = _cache_put(
            _CachedResult(
                composite_bytes=result.composite_bytes,
                composite_mime=result.composite_mime,
                mask_bytes=result.mask_bytes,
            )
        )
        base = str(request.base_url).rstrip("/")
        return {
            "composite_url": f"{base}/api/result/{token}/composite.png",
            "mask_url": f"{base}/api/result/{token}/mask.png" if result.mask_bytes else None,
            "text": result.text or "",
        }

    @app.get("/api/result/{token}/composite.png")
    async def fetch_composite(token: str) -> Response:
        cached = _RESULT_CACHE.get(token)
        if not cached:
            raise HTTPException(status_code=404, detail="Result expired or not found.")
        return Response(content=cached.composite_bytes, media_type=cached.composite_mime)

    @app.get("/api/result/{token}/mask.png")
    async def fetch_mask(token: str) -> Response:
        cached = _RESULT_CACHE.get(token)
        if not cached:
            raise HTTPException(status_code=404, detail="Result expired or not found.")
        if not cached.mask_bytes:
            raise HTTPException(status_code=404, detail="No mask was generated for this result.")
        return Response(content=cached.mask_bytes, media_type="image/png")

    return app


# Convenience for `uvicorn ai_edit.server.app:app`.
app = create_app()
