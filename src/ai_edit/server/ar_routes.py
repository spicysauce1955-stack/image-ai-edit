"""AR delivery routes.

Phase 1 + 6.A of the AR plan.

Routes mounted under ``/ar``:

``GET /ar/{scene_id}``
    Model-viewer HTML page wired for OS-delegated AR (Quick Look on
    iOS, Scene Viewer on Android, WebXR where supported). Phase 1.

``GET /ar/{scene_id}/live``
    Three.js + WebXR page with ``immersive-ar`` + ``hit-test``: tap a
    detected surface to place the model in your space. Browser stays
    in our app the whole time — the OS native viewer is not invoked.
    Phase 6.A.

``GET /ar/{scene_id}/model.glb``
    Serves the GLB bytes with ``model/gltf-binary``.

``GET /ar/{scene_id}/model.usdz``
    Serves the USDZ bytes with ``model/vnd.usdz+zip``.

The router is created via :func:`build_ar_router` so tests can inject a
fresh :class:`ARStore` per test — see ``tests/server/test_ar_routes.py``.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import HTMLResponse, Response

from ..models.base import MIME_GLB, MIME_USDZ
from ..pipeline.ar_store import ARStore, SCENE_ID_PATTERN

_log = logging.getLogger("ai_edit.ar")

# A FastAPI Annotated alias so all three routes use the same validator
# without repeating the regex.
SceneId = Annotated[str, Path(pattern=SCENE_ID_PATTERN)]


# Pinned three.js version for the live AR page. Bumping is a deliberate
# change — every three.js minor can shift WebXR / hit-test behaviour.
_THREE_VERSION = "0.160.0"


def _render_live_html(scene_id: str) -> str:
    """Build the three.js + WebXR live placement page for ``scene_id``.

    Loads the catalog entry's GLB through the existing
    ``/ar/{scene_id}/model.glb`` route and enters an ``immersive-ar``
    session with ``hit-test`` so the user can place the model on a
    detected surface. ARButton handles the no-support fallback —
    iOS Safari users see "AR not supported" and we keep the
    Quick-Look-via-``/ar/{scene_id}`` path as the canonical iOS UX.
    """
    safe_id = html.escape(scene_id, quote=True)
    safe_three = html.escape(_THREE_VERSION, quote=True)
    # JS string literal — json.dumps gives us a properly quoted /
    # escaped form. For our regex-safe scene_ids this is identical
    # to a plain double-quoted string; the dependency keeps it safe
    # if the scene-id rule ever loosens.
    scene_id_js = json.dumps(scene_id)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Live AR — {safe_id}</title>
<style>
  :root {{ color-scheme: dark; }}
  html, body {{ margin: 0; height: 100%; overflow: hidden; background: #111;
                color: #eee; font: 14px/1.4 -apple-system, BlinkMacSystemFont,
                "Segoe UI", sans-serif; }}
  canvas {{ display: block; }}
  #info {{ position: fixed; top: 12px; left: 12px; right: 12px;
           display: flex; justify-content: space-between; align-items: center;
           pointer-events: none; z-index: 5; }}
  #info .title {{ font-weight: 600; pointer-events: auto;
                  background: rgba(0,0,0,0.45); padding: 6px 10px;
                  border-radius: 16px; }}
  #info .back {{ color: #eee; opacity: 0.85; text-decoration: none;
                 pointer-events: auto; background: rgba(0,0,0,0.45);
                 padding: 6px 10px; border-radius: 16px; }}
  #info .back:hover {{ opacity: 1; }}
  #overlay {{ position: fixed; inset: 0; z-index: 4; pointer-events: none; }}
  #overlay > * {{ pointer-events: auto; }}
  #status {{ position: absolute; left: 50%; bottom: 96px; transform: translateX(-50%);
             background: rgba(0,0,0,0.55); padding: 8px 14px; border-radius: 12px;
             font-size: 13px; max-width: 80vw; text-align: center; }}
  #panel {{ position: absolute; right: 12px; bottom: 96px; width: 240px;
            background: rgba(0,0,0,0.65); padding: 12px 14px; border-radius: 12px;
            backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
            display: flex; flex-direction: column; gap: 10px; font-size: 12px; }}
  #panel label {{ display: flex; flex-direction: column; gap: 4px; color: #ddd; }}
  #panel label span.row {{ display: flex; justify-content: space-between;
                           font-size: 11px; opacity: 0.8; }}
  #panel select, #panel input[type=range] {{ width: 100%; }}
  #panel select {{ background: #222; color: #eee; border: 1px solid #333;
                   padding: 6px; border-radius: 6px; }}
  #panel button {{ background: #fff; color: #111; border: 0; padding: 8px;
                   border-radius: 8px; font-weight: 600; cursor: pointer; }}
  #panel button.ghost {{ background: transparent; color: #ddd;
                         border: 1px solid #444; font-weight: 500; }}
  @media (max-width: 480px) {{
    #panel {{ left: 12px; right: 12px; width: auto; bottom: 96px; }}
    #status {{ bottom: 220px; }}
  }}
  /* ARButton injects an absolutely-positioned button — match the
     model-viewer pill style so the two AR pages feel related. */
  button.xr-button, .xr-button {{ position: fixed !important;
    bottom: 24px !important; left: 50% !important;
    transform: translateX(-50%) !important;
    padding: 12px 24px !important; border: 0 !important;
    border-radius: 24px !important; background: #fff !important;
    color: #111 !important; font: 600 14px -apple-system, sans-serif !important;
    z-index: 6 !important; cursor: pointer; }}
</style>
<script type="importmap">
{{
  "imports": {{
    "three": "https://unpkg.com/three@{safe_three}/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@{safe_three}/examples/jsm/"
  }}
}}
</script>
</head>
<body>
<div id="info">
  <div class="title">Live AR · {safe_id}</div>
  <a class="back" href="/ar/{safe_id}">← viewer</a>
</div>
<div id="overlay">
  <div id="status">Loading model…</div>
  <div id="panel">
    <label>
      <span class="row"><span>Model</span></span>
      <select id="model-select"></select>
    </label>
    <label>
      <span class="row"><span>Scale</span><span id="scale-val">1.00×</span></span>
      <input id="scale-slider" type="range" min="0.1" max="3" step="0.05" value="1">
    </label>
    <label>
      <span class="row"><span>Rotate Y</span><span id="rot-val">0°</span></span>
      <input id="rot-slider" type="range" min="-180" max="180" step="1" value="0">
    </label>
    <button id="reset-btn" class="ghost" type="button">Reset placement</button>
  </div>
</div>
<script type="module">
import * as THREE from 'three';
import {{ ARButton }} from 'three/addons/webxr/ARButton.js';
import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

// Mutable so the model dropdown can swap the active asset without a
// page reload. Initial value baked at render time from the route.
let SCENE_ID = {scene_id_js};
const modelUrlFor = (id) => `/ar/${{id}}/model.glb`;
const statusEl = document.getElementById('status');
const setStatus = (m) => {{ statusEl.textContent = m; }};

// Single source of truth for all configurable parameters. Sliders +
// future touch gestures write here; the render loop applies on every
// frame so changes show up instantly on preview and placed instances.
const state = {{
  scale: 1.0,
  rotationY: 0,  // radians
}};

const renderer = new THREE.WebGLRenderer({{ alpha: true, antialias: true }});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.xr.enabled = true;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(
  70, window.innerWidth / window.innerHeight, 0.01, 100);
camera.position.set(0, 1.2, 2.5);

scene.add(new THREE.HemisphereLight(0xffffff, 0xbbbbff, 1.0));
const dir = new THREE.DirectionalLight(0xffffff, 1.0);
dir.position.set(5, 10, 7);
scene.add(dir);

// Non-AR preview: free-orbit camera so the page is useful even when
// WebXR isn't available (desktops, iOS Safari today).
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.5, 0);
controls.update();

// Reticle indicating where a tap will place the model in AR.
const reticle = new THREE.Mesh(
  new THREE.RingGeometry(0.07, 0.10, 32).rotateX(-Math.PI / 2),
  new THREE.MeshBasicMaterial({{ color: 0xffffff }})
);
reticle.matrixAutoUpdate = false;
reticle.visible = false;
scene.add(reticle);

// Load the model. We keep a template and clone it on each placement
// so that 6.C (multi-object composition) can reuse the same path.
const loader = new GLTFLoader();
let modelTemplate = null;
let previewClone = null;
let placedModel = null;

function applyState(obj) {{
  if (!obj) return;
  obj.scale.setScalar(state.scale);
  obj.rotation.y = state.rotationY;
}}

function loadModel(sceneId, {{ initial = false }} = {{}}) {{
  SCENE_ID = sceneId;
  setStatus('Loading model…');
  if (placedModel) {{ scene.remove(placedModel); placedModel = null; }}
  if (previewClone) {{ scene.remove(previewClone); previewClone = null; }}
  modelTemplate = null;
  loader.load(
    modelUrlFor(sceneId),
    (gltf) => {{
      modelTemplate = gltf.scene;
      previewClone = modelTemplate.clone();
      applyState(previewClone);
      scene.add(previewClone);
      setStatus(initial
        ? 'Tap "START AR" to place in your space.'
        : `Loaded ${{sceneId}}.`);
      if (!initial) {{
        // Keep the URL in sync so reload reflects current selection.
        history.replaceState(null, '', `/ar/${{sceneId}}/live`);
        document.title = `Live AR — ${{sceneId}}`;
      }}
    }},
    undefined,
    (err) => setStatus('Failed to load model: ' + (err.message || err))
  );
}}

loadModel(SCENE_ID, {{ initial: true }});

// HUD wiring
const modelSelect = document.getElementById('model-select');
const scaleSlider = document.getElementById('scale-slider');
const scaleVal = document.getElementById('scale-val');
const rotSlider = document.getElementById('rot-slider');
const rotVal = document.getElementById('rot-val');
const resetBtn = document.getElementById('reset-btn');

scaleSlider.addEventListener('input', () => {{
  state.scale = parseFloat(scaleSlider.value);
  scaleVal.textContent = state.scale.toFixed(2) + '×';
  applyState(previewClone);
  applyState(placedModel);
}});

rotSlider.addEventListener('input', () => {{
  const deg = parseFloat(rotSlider.value);
  state.rotationY = deg * Math.PI / 180;
  rotVal.textContent = deg + '°';
  applyState(previewClone);
  applyState(placedModel);
}});

resetBtn.addEventListener('click', () => {{
  if (placedModel) {{ scene.remove(placedModel); placedModel = null; }}
  setStatus('Placement cleared.');
}});

// Populate the model dropdown from the catalog API. Falls back to the
// current scene as the only option if the API fetch fails.
fetch('/api/catalog')
  .then((r) => r.ok ? r.json() : [])
  .then((entries) => {{
    if (!Array.isArray(entries) || entries.length === 0) {{
      const opt = document.createElement('option');
      opt.value = SCENE_ID; opt.textContent = SCENE_ID; opt.selected = true;
      modelSelect.appendChild(opt);
      return;
    }}
    // Group by category for clearer browsing.
    const groups = new Map();
    entries.forEach((e) => {{
      if (!groups.has(e.category)) groups.set(e.category, []);
      groups.get(e.category).push(e);
    }});
    for (const [category, items] of groups) {{
      const group = document.createElement('optgroup');
      group.label = category;
      items.forEach((entry) => {{
        const opt = document.createElement('option');
        opt.value = entry.id;
        opt.textContent = entry.name;
        if (entry.id === SCENE_ID) opt.selected = true;
        group.appendChild(opt);
      }});
      modelSelect.appendChild(group);
    }}
  }})
  .catch(() => {{
    const opt = document.createElement('option');
    opt.value = SCENE_ID; opt.textContent = SCENE_ID; opt.selected = true;
    modelSelect.appendChild(opt);
  }});

modelSelect.addEventListener('change', () => {{
  loadModel(modelSelect.value);
}});

// ARButton injects itself into the DOM and manages session start/end.
const arButton = ARButton.createButton(renderer, {{
  requiredFeatures: ['hit-test'],
  optionalFeatures: ['dom-overlay'],
  domOverlay: {{ root: document.getElementById('overlay') }}
}});
arButton.classList.add('xr-button');
document.body.appendChild(arButton);

let hitTestSource = null;
let localSpace = null;

renderer.xr.addEventListener('sessionstart', async () => {{
  setStatus('Move the phone around to find a surface, then tap.');
  if (previewClone) previewClone.visible = false;
  const session = renderer.xr.getSession();
  const viewerSpace = await session.requestReferenceSpace('viewer');
  hitTestSource = await session.requestHitTestSource({{ space: viewerSpace }});
  localSpace = await session.requestReferenceSpace('local');
}});

renderer.xr.addEventListener('sessionend', () => {{
  hitTestSource = null;
  localSpace = null;
  if (placedModel) {{ scene.remove(placedModel); placedModel = null; }}
  if (previewClone) previewClone.visible = true;
  reticle.visible = false;
  setStatus('Out of AR. Tap "START AR" again to retry.');
}});

// Controller exposes the "select" event for taps inside an AR session.
const controller = renderer.xr.getController(0);
controller.addEventListener('select', () => {{
  if (!reticle.visible || !modelTemplate) return;
  if (placedModel) scene.remove(placedModel);
  placedModel = modelTemplate.clone();
  placedModel.position.setFromMatrixPosition(reticle.matrix);
  applyState(placedModel);
  scene.add(placedModel);
  setStatus('Placed. Adjust with the panel; tap to relocate.');
}});
scene.add(controller);

renderer.setAnimationLoop((time, frame) => {{
  if (frame && hitTestSource && localSpace) {{
    const hits = frame.getHitTestResults(hitTestSource);
    if (hits.length) {{
      const pose = hits[0].getPose(localSpace);
      reticle.visible = true;
      reticle.matrix.fromArray(pose.transform.matrix);
    }} else {{
      reticle.visible = false;
    }}
  }} else {{
    controls.update();
  }}
  renderer.render(scene, camera);
}});

window.addEventListener('resize', () => {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}});
</script>
</body>
</html>
"""


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
<div class="hint">
  scene: {safe_id} · <a href="/ar/{safe_id}/live"
    style="color:#eee;text-decoration:underline;text-decoration-color:#444;
    pointer-events:auto;">live AR (WebXR)</a>
</div>
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
            _log.info("ar.viewer status=404 scene=%s", scene_id)
            raise HTTPException(status_code=404, detail=f"Unknown scene: {scene_id}")
        _log.info("ar.viewer status=200 scene=%s", scene_id)
        return HTMLResponse(_render_viewer_html(scene_id))

    @router.get("/{scene_id}/live", response_class=HTMLResponse)
    async def ar_live(scene_id: SceneId) -> HTMLResponse:
        """Return the three.js + WebXR live placement page for ``scene_id``.

        Same 404 semantics as the model-viewer route — the page would
        load but the GLB fetch inside it would 404, so we'd rather
        fail before serving HTML.
        """
        if not store.exists(scene_id):
            _log.info("ar.live status=404 scene=%s", scene_id)
            raise HTTPException(status_code=404, detail=f"Unknown scene: {scene_id}")
        _log.info("ar.live status=200 scene=%s", scene_id)
        return HTMLResponse(_render_live_html(scene_id))

    @router.get("/{scene_id}/model.glb")
    async def ar_glb(scene_id: SceneId) -> Response:
        """Serve the GLB bytes for ``scene_id``."""
        data = store.get(scene_id, MIME_GLB)
        if data is None:
            _log.info("ar.glb status=404 scene=%s", scene_id)
            raise HTTPException(status_code=404, detail=f"No GLB for scene: {scene_id}")
        _log.info("ar.glb status=200 scene=%s bytes=%d", scene_id, len(data))
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
            _log.info("ar.usdz status=404 scene=%s", scene_id)
            raise HTTPException(status_code=404, detail=f"No USDZ for scene: {scene_id}")
        _log.info("ar.usdz status=200 scene=%s bytes=%d", scene_id, len(data))
        return Response(content=data, media_type=MIME_USDZ)

    return router
