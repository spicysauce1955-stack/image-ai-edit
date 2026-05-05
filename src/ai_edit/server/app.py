"""FastAPI app wrapping the insertion pipeline.

Endpoints
---------
``GET /``
    Drag-drop UI. Lets the user upload a scene + reference, draw a
    polygon, pick a mode, edit the system prompt, and run the pipeline.

``POST /api/insert``
    Multipart upload for one composite generation. See the field table
    below. Returns a JSON envelope with one-shot URLs for the bytes:
    ``{composite_url, aux_url, aux_kind, text}``.

``GET /api/result/{token}/composite.png``
``GET /api/result/{token}/aux.png``
    One-shot fetches for the bytes referenced from the JSON envelope.

``GET /api/defaults``
    Default system prompts for free / mask / refine. Used by the UI
    to pre-fill the system-prompt textarea.

``GET /healthz``
    Liveness probe.

State
-----
A small in-memory result cache keyed by random token. Tokens evict on
process restart and FIFO-evict when the cache is full.
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
from ..pipeline.insert import (
    DEFAULT_FREE_PROMPT,
    DEFAULT_MASK_PROMPT,
    DEFAULT_REFINE_PROMPT,
)

STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class _CachedResult:
    composite_bytes: bytes
    composite_mime: str
    aux_bytes: bytes  # the binary mask; empty for free / refine
    aux_kind: str | None  # "mask" | None


_RESULT_CACHE: dict[str, _CachedResult] = {}
_CACHE_CAP = 64


def _cache_put(result: _CachedResult) -> str:
    """Stash a result and return an opaque token."""
    if len(_RESULT_CACHE) >= _CACHE_CAP:
        _RESULT_CACHE.pop(next(iter(_RESULT_CACHE)))
    token = secrets.token_urlsafe(16)
    _RESULT_CACHE[token] = result
    return token


def _parse_polygon(raw: str) -> list[tuple[float, float]] | None:
    """Parse ``polygon`` form field. Empty → None.

    Raises 400 with a clear message on bad payloads so the UI can
    surface them inline.
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
            raise HTTPException(status_code=400, detail=f"Bad polygon vertex: {p!r}")
        u, v = float(p[0]), float(p[1])
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise HTTPException(
                status_code=400,
                detail=f"Polygon vertices must be normalized to [0, 1]: got {p!r}",
            )
        points.append((u, v))
    return points


VALID_MODES: set[str] = {"free", "mask"}
VALID_MASK_ENGINES: set[str] = {"openai", "flux_prepaste"}


def create_app() -> FastAPI:
    """Build and return the FastAPI app."""
    load_env()
    app = FastAPI(title="image-ai-edit", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/defaults")
    async def defaults() -> dict[str, str]:
        """Default system prompts for each mode + refinement."""
        return {
            "free": DEFAULT_FREE_PROMPT,
            "mask": DEFAULT_MASK_PROMPT,
            "refine": DEFAULT_REFINE_PROMPT,
        }

    @app.post("/api/insert")
    async def insert(
        request: Request,
        scene: UploadFile = File(...),
        reference: UploadFile = File(...),
        instruction: str = Form(...),
        mode: str = Form("free"),
        polygon: str = Form(""),
        system_prompt: str = Form(""),
        segment: str = Form(""),
        relight: str = Form(""),
        reference_crop: str = Form(""),
        mask_engine: str = Form("openai"),
        previous: UploadFile | None = File(None),
    ) -> dict[str, str | None]:
        """Run the insertion pipeline.

        Required: ``scene``, ``reference``, ``instruction``.
        Mode: ``free`` (default, Gemini picks placement) or ``mask``
        (FLUX-Kontext-LoRA inpaint, hard polygon constraint).
        ``mask`` requires a polygon.

        Returns a JSON envelope with one-shot URLs for the composite
        and (when relevant) the auxiliary image actually sent to the
        model.
        """
        if mode not in VALID_MODES:
            raise HTTPException(
                status_code=400, detail=f"Unknown mode: {mode!r}. Try {sorted(VALID_MODES)}."
            )
        polygon_pts = _parse_polygon(polygon)
        if mode == "mask" and not polygon_pts:
            raise HTTPException(
                status_code=400, detail="mode='mask' requires a polygon (≥3 vertices)."
            )
        if mask_engine not in VALID_MASK_ENGINES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown mask_engine: {mask_engine!r}. Try {sorted(VALID_MASK_ENGINES)}.",
            )

        scene_bytes = await scene.read()
        reference_bytes = await reference.read()
        previous_bytes = await previous.read() if previous is not None else None
        previous_mime = (previous.content_type or "image/png") if previous else "image/png"

        seg_prompts = [s.strip() for s in segment.split(",") if s.strip()]
        relight_prompt = relight.strip() or None
        custom_system_prompt = system_prompt.strip() or None

        ref_crop: tuple[float, float] | None = None
        if reference_crop.strip():
            try:
                parts = [float(x) for x in reference_crop.split(",")]
                if len(parts) != 2 or not (0 <= parts[0] < parts[1] <= 1):
                    raise ValueError
                ref_crop = (parts[0], parts[1])
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "reference_crop must be 'top,bottom' with "
                        "0 <= top < bottom <= 1, e.g. '0.30,0.85'."
                    ),
                )

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
                    mode=mode,  # type: ignore[arg-type]
                    mask_polygon=polygon_pts,
                    system_prompt=custom_system_prompt,
                    reference_crop=ref_crop,
                    mask_engine=mask_engine,  # type: ignore[arg-type]
                    previous_composite=previous_bytes,
                    previous_mime=previous_mime,
                    segmentation_prompts=seg_prompts or None,
                    relight_prompt=relight_prompt,
                )
            except HTTPException:
                raise
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        token = _cache_put(
            _CachedResult(
                composite_bytes=result.composite_bytes,
                composite_mime=result.composite_mime,
                aux_bytes=result.aux_bytes,
                aux_kind=result.aux_kind,
            )
        )
        base = str(request.base_url).rstrip("/")
        return {
            "composite_url": f"{base}/api/result/{token}/composite.png",
            "aux_url": f"{base}/api/result/{token}/aux.png" if result.aux_bytes else None,
            "aux_kind": result.aux_kind,
            "text": result.text or "",
        }

    @app.get("/api/result/{token}/composite.png")
    async def fetch_composite(token: str) -> Response:
        cached = _RESULT_CACHE.get(token)
        if not cached:
            raise HTTPException(status_code=404, detail="Result expired or not found.")
        return Response(content=cached.composite_bytes, media_type=cached.composite_mime)

    @app.get("/api/result/{token}/aux.png")
    async def fetch_aux(token: str) -> Response:
        cached = _RESULT_CACHE.get(token)
        if not cached:
            raise HTTPException(status_code=404, detail="Result expired or not found.")
        if not cached.aux_bytes:
            raise HTTPException(status_code=404, detail="No aux image for this result.")
        return Response(content=cached.aux_bytes, media_type="image/png")

    return app


# Convenience for `uvicorn ai_edit.server.app:app`.
app = create_app()
