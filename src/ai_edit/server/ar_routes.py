"""AR delivery routes.

Phase 1 of the AR plan: serve a ``<model-viewer>`` HTML page plus the
GLB and USDZ asset bytes from an :class:`ARStore`. No 3D generation
here — that's Phase 2.

Routes mounted under ``/ar``:

``GET /ar/{scene_id}``
    HTML page wired with the model-viewer web component, including the
    iOS Quick Look and Android Scene Viewer / WebXR handoffs.

``GET /ar/{scene_id}/model.glb``
    Serves the GLB bytes with ``model/gltf-binary``.

``GET /ar/{scene_id}/model.usdz``
    Serves the USDZ bytes with ``model/vnd.usdz+zip``.

The router is created via :func:`build_ar_router` so tests can inject a
fresh :class:`ARStore` per test — see ``tests/server/test_ar_routes.py``.
"""

from __future__ import annotations

import html
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import HTMLResponse, Response

from ..models.base import MIME_GLB, MIME_USDZ
from ..pipeline.ar_store import ARStore

# Regex used as both the FastAPI path-param validator and an explicit
# defence against path traversal. Sixty-four chars covers a UUID hex
# (32) or a 22-char base64-url token with room to spare.
SCENE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

# A FastAPI Annotated alias so all three routes use the same validator
# without repeating the regex.
SceneId = Annotated[str, Path(pattern=SCENE_ID_PATTERN)]


def _render_viewer_html(scene_id: str) -> str:
    """Build the ``<model-viewer>`` page for ``scene_id``.

    ``scene_id`` is regex-validated upstream but we still
    ``html.escape`` it — defence in depth in case the validator is
    ever loosened.

    Why the attribute soup matters:

    - ``src``       — GLB used by WebXR + Android Scene Viewer.
    - ``ios-src``   — USDZ Apple Quick Look hands off to.
    - ``ar``        — enable the "View in your space" button.
    - ``ar-modes``  — explicit fallback order. ``webxr`` is tried first
      where the browser exposes it (Quest Browser, some Chrome
      Android), then ``scene-viewer`` (Android native), then
      ``quick-look`` (iOS).
    - ``camera-controls`` + ``auto-rotate`` — keeps the 3D preview
      interactive when the user is still on the page (not yet in AR).
    """
    safe_id = html.escape(scene_id, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AR preview — {safe_id}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #111; color: #eee;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  model-viewer {{ width: 100vw; height: 100vh; background: #111; }}
  .hint {{ position: fixed; left: 12px; bottom: 12px; font-size: 13px;
           opacity: 0.6; pointer-events: none; }}
</style>
<script type="module"
  src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js"></script>
</head>
<body>
<model-viewer
  src="/ar/{safe_id}/model.glb"
  ios-src="/ar/{safe_id}/model.usdz"
  ar
  ar-modes="webxr scene-viewer quick-look"
  camera-controls
  auto-rotate
  shadow-intensity="1"
  exposure="1"
  alt="AR preview for scene {safe_id}">
  <button slot="ar-button" style="position:absolute;bottom:24px;right:24px;
    padding:12px 18px;border:0;border-radius:24px;background:#fff;color:#111;
    font-weight:600;">View in your space</button>
</model-viewer>
<div class="hint">scene: {safe_id}</div>
</body>
</html>
"""


def build_ar_router(store: ARStore) -> APIRouter:
    """Construct the AR router with ``store`` baked in.

    Returning a fresh router per call makes the tests trivially
    isolated — each test can build its own store and router without
    touching module state.
    """
    router = APIRouter(prefix="/ar", tags=["ar"])

    @router.get("/{scene_id}", response_class=HTMLResponse)
    async def ar_viewer(scene_id: SceneId) -> HTMLResponse:
        """Return the ``<model-viewer>`` HTML page for ``scene_id``.

        404 if the scene has no assets at all — the page would
        otherwise render but the model-viewer would error out, which
        is a worse UX than a clean not-found.
        """
        if not store.exists(scene_id):
            raise HTTPException(status_code=404, detail=f"Unknown scene: {scene_id}")
        return HTMLResponse(_render_viewer_html(scene_id))

    @router.get("/{scene_id}/model.glb")
    async def ar_glb(scene_id: SceneId) -> Response:
        """Serve the GLB bytes for ``scene_id``."""
        data = store.get(scene_id, MIME_GLB)
        if data is None:
            raise HTTPException(status_code=404, detail=f"No GLB for scene: {scene_id}")
        return Response(content=data, media_type=MIME_GLB)

    @router.get("/{scene_id}/model.usdz")
    async def ar_usdz(scene_id: SceneId) -> Response:
        """Serve the USDZ bytes for ``scene_id``.

        Missing USDZ is *not* fatal — the GLB path still serves the
        3D preview, just without an iOS Quick Look handoff. Return
        404 so model-viewer falls back cleanly.
        """
        data = store.get(scene_id, MIME_USDZ)
        if data is None:
            raise HTTPException(status_code=404, detail=f"No USDZ for scene: {scene_id}")
        return Response(content=data, media_type=MIME_USDZ)

    return router
