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
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from ..config import load_env
from ..pipeline import insert_object
from ..pipeline.ar_store import ARStore, FilesystemARStore
from ..pipeline.asset_catalog import AssetCatalog
from ..pipeline.insert import (
    DEFAULT_FREE_PROMPT,
    DEFAULT_MASK_PROMPT,
    DEFAULT_OVERLAY_PROMPT,
    DEFAULT_REFINE_PROMPT,
)
from .ar_routes import build_ar_router
from .catalog_routes import build_catalog_api_router, build_catalog_browse_router
from .logging_setup import setup_logging

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_AR_ROOT = Path.cwd() / "out" / "scenes"


@dataclass
class _CachedResult:
    composite_bytes: bytes
    composite_mime: str
    aux_bytes: bytes  # the binary mask; empty for free / refine
    aux_kind: str | None  # "mask" | None
    composite_fetched: bool = False
    aux_fetched: bool = False


_RESULT_CACHE: OrderedDict[str, _CachedResult] = OrderedDict()
_CACHE_CAP = 64
_CACHE_MAX_BYTES = 256 * 1024 * 1024
_MAX_UPLOAD_BYTES = 32 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000
_SAFE_IMAGE_SUFFIXES = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


def _cache_put(result: _CachedResult) -> str:
    """Stash a result and return an opaque token."""
    result_size = len(result.composite_bytes) + len(result.aux_bytes)
    while _RESULT_CACHE and (
        len(_RESULT_CACHE) >= _CACHE_CAP
        or _cache_size_bytes() + result_size > _CACHE_MAX_BYTES
    ):
        _RESULT_CACHE.pop(next(iter(_RESULT_CACHE)))
    token = secrets.token_urlsafe(16)
    _RESULT_CACHE[token] = result
    return token


def _cache_size_bytes() -> int:
    """Return total binary payload bytes retained by the in-memory cache."""
    return sum(len(r.composite_bytes) + len(r.aux_bytes) for r in _RESULT_CACHE.values())


def _maybe_evict_fetched(token: str, result: _CachedResult) -> None:
    """Delete a token once all available one-shot resources were fetched."""
    aux_done = not result.aux_bytes or result.aux_fetched
    if result.composite_fetched and aux_done:
        _RESULT_CACHE.pop(token, None)


async def _read_upload_limited(
    upload: UploadFile,
    *,
    label: str,
    max_bytes: int = _MAX_UPLOAD_BYTES,
) -> bytes:
    """Read an upload in chunks and reject oversized bodies with 413."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{label} image is too large; limit is {max_bytes // (1024 * 1024)} MiB.",
            )
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail=f"{label} image is empty.")
    return b"".join(chunks)


def _validate_image_bytes(data: bytes, *, label: str) -> None:
    """Ensure uploaded bytes are an image and keep decompression bounded."""
    try:
        with Image.open(BytesIO(data)) as img:
            width, height = img.size
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be a valid image.") from exc
    if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"{label} image dimensions are too large; "
                f"limit is {_MAX_IMAGE_PIXELS:,} pixels."
            ),
        )


def _upload_path(tmp_path: Path, upload: UploadFile, stem: str) -> Path:
    """Build a server-controlled temp path while preserving a safe suffix."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in _SAFE_IMAGE_SUFFIXES:
        suffix = ".bin"
    return tmp_path / f"{stem}{suffix}"


def _parse_uv_list(raw: str, *, min_count: int, label: str) -> list[tuple[float, float]] | None:
    """Parse a JSON list of ``[u, v]`` pairs in ``[0, 1]``.

    Used by both ``polygon`` (legacy) and ``poles`` form fields.
    Empty string returns None (caller decides if that's acceptable).
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label} JSON: {exc}")
    if not isinstance(parsed, list) or len(parsed) < min_count:
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be a JSON list of at least {min_count} [u, v] pairs.",
        )
    points: list[tuple[float, float]] = []
    for p in parsed:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise HTTPException(status_code=400, detail=f"Bad {label} vertex: {p!r}")
        try:
            u, v = float(p[0]), float(p[1])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Bad {label} vertex: {p!r}") from exc
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise HTTPException(
                status_code=400,
                detail=f"{label} vertices must be normalized to [0, 1]: got {p!r}",
            )
        points.append((u, v))
    return points


def _parse_polygon(raw: str) -> list[tuple[float, float]] | None:
    return _parse_uv_list(raw, min_count=3, label="polygon")


def _parse_poles(raw: str) -> list[tuple[float, float]] | None:
    return _parse_uv_list(raw, min_count=2, label="poles")


VALID_MODES: set[str] = {"free", "mask", "overlay"}
VALID_MASK_ENGINES: set[str] = {
    "gpt_image_2",
    "gemini_translucent",
    "flux_ref_inpaint",
    "gemini_crop",
    "anydoor_chain",
    "gpt_fal",
    "anydoor",
    "openai",
    "flux_prepaste",
}


def create_app(
    ar_store: ARStore | None = None,
    catalog: AssetCatalog | None = None,
) -> FastAPI:
    """Build and return the FastAPI app.

    ``ar_store`` lets tests inject an isolated AR store backed by
    ``tmp_path`` instead of the on-disk ``out/scenes/`` directory.
    Production callers pass nothing and get the default filesystem
    store rooted at ``out/scenes``.

    ``catalog`` similarly lets tests inject a controlled
    :class:`AssetCatalog`; the default loads the in-tree manifest at
    ``assets/catalog.json``.
    """
    load_env()
    setup_logging()
    app = FastAPI(title="image-ai-edit", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    # ``or`` is wrong here — an empty AssetCatalog is falsy (it
    # defines __len__), which would silently fall back to the on-disk
    # manifest. Use explicit ``is None`` checks for both.
    ar_store_instance = ar_store if ar_store is not None else FilesystemARStore(DEFAULT_AR_ROOT)
    catalog_instance = catalog if catalog is not None else AssetCatalog.load()
    app.include_router(build_ar_router(ar_store_instance))
    app.include_router(build_catalog_api_router(catalog_instance))
    app.include_router(build_catalog_browse_router(catalog_instance))

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
            "overlay": DEFAULT_OVERLAY_PROMPT,
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
        poles: str = Form(""),
        pole_section_height: float = Form(0.18),
        overlay_alpha: float = Form(0.85),
        system_prompt: str = Form(""),
        segment: str = Form(""),
        relight: str = Form(""),
        reference_crop: str = Form(""),
        mask_engine: str = Form("gpt_image_2"),
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
        poles_pts = _parse_poles(poles)
        if mode in ("mask", "overlay") and not (polygon_pts or poles_pts):
            raise HTTPException(
                status_code=400,
                detail=f"mode={mode!r} requires either a polygon (≥3 vertices) or poles (≥2 points).",
            )
        if mode == "overlay" and not poles_pts:
            raise HTTPException(
                status_code=400,
                detail="mode='overlay' requires poles (perspective warp uses pole geometry).",
            )
        if mask_engine not in VALID_MASK_ENGINES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown mask_engine: {mask_engine!r}. Try {sorted(VALID_MASK_ENGINES)}.",
            )

        scene_bytes = await _read_upload_limited(scene, label="scene")
        reference_bytes = await _read_upload_limited(reference, label="reference")
        previous_bytes = (
            await _read_upload_limited(previous, label="previous")
            if previous is not None
            else None
        )
        previous_mime = (previous.content_type or "image/png") if previous else "image/png"
        _validate_image_bytes(scene_bytes, label="scene")
        _validate_image_bytes(reference_bytes, label="reference")
        if previous_bytes is not None:
            _validate_image_bytes(previous_bytes, label="previous")

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
            scene_path = _upload_path(tmp_path, scene, "scene")
            reference_path = _upload_path(tmp_path, reference, "reference")
            scene_path.write_bytes(scene_bytes)
            reference_path.write_bytes(reference_bytes)

            try:
                result = await insert_object(
                    scene_path,
                    reference_path,
                    instruction,
                    mode=mode,  # type: ignore[arg-type]
                    mask_polygon=polygon_pts,
                    poles=poles_pts,
                    pole_section_height=pole_section_height,
                    overlay_alpha=overlay_alpha,
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
        if cached.composite_fetched:
            raise HTTPException(status_code=404, detail="Composite already fetched.")
        cached.composite_fetched = True
        content = cached.composite_bytes
        media_type = cached.composite_mime
        _maybe_evict_fetched(token, cached)
        return Response(content=content, media_type=media_type)

    @app.get("/api/result/{token}/aux.png")
    async def fetch_aux(token: str) -> Response:
        cached = _RESULT_CACHE.get(token)
        if not cached:
            raise HTTPException(status_code=404, detail="Result expired or not found.")
        if not cached.aux_bytes:
            raise HTTPException(status_code=404, detail="No aux image for this result.")
        if cached.aux_fetched:
            raise HTTPException(status_code=404, detail="Aux image already fetched.")
        cached.aux_fetched = True
        content = cached.aux_bytes
        _maybe_evict_fetched(token, cached)
        return Response(content=content, media_type="image/png")

    return app


# Convenience for `uvicorn ai_edit.server.app:app`.
app = create_app()
