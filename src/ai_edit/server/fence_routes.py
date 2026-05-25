"""Multi-section fence routes (Phase 8.C).

Two additive HTTP surfaces, both new — nothing in :mod:`ar_routes`
(``/ar/{id}``, ``/ar/{id}/live``) or the catalog routes is modified:

``POST /api/fence/layout``
    Thin wrapper over :func:`ai_edit.pipeline.fence.compute_fence_layout`.
    Body is a ``FenceSpec`` JSON (panel + post component refs + a ground
    path); returns the computed ``FenceLayout`` (post + panel transforms
    and counts). The pure layout engine is the **single source of
    truth** — the WebXR page calls this rather than re-implementing the
    geometry in JS, so the two can never drift.

``GET /ar/{base_id}/fence``
    A three.js + WebXR page that assembles a straight fence run from the
    ``<base>__panel`` / ``<base>__post`` components (built by Phase 8.B).
    Tap a surface for the start, tap again for the end; the page POSTs
    the two points to ``/api/fence/layout`` and builds two
    ``THREE.InstancedMesh`` batches (posts, panels). Stays
    extension-free so it loads through the same bare ``GLTFLoader`` the
    ``/live`` page uses.

The router is built via :func:`build_fence_router` so tests inject a
fresh :class:`ARStore` per test, mirroring :func:`build_ar_router`.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..pipeline.ar_store import ARStore, SCENE_ID_PATTERN
from ..pipeline.fence import (
    ComponentRef,
    FenceSpec,
    Transform,
    compute_fence_layout,
)
from ..pipeline.fence_components import panel_component_id, post_component_id

_log = logging.getLogger("ai_edit.fence")

SceneId = Annotated[str, Path(pattern=SCENE_ID_PATTERN)]

# Same pinned three.js as the /live page — bumping is a deliberate
# change since each minor can shift WebXR / hit-test behaviour.
_THREE_VERSION = "0.160.0"


# --- request / response models --------------------------------------------


class ComponentRefIn(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)
    nominal_width: float = Field(gt=0.0)


class FenceSpecIn(BaseModel):
    """Wire form of :class:`ai_edit.pipeline.fence.FenceSpec`.

    Pydantic handles shape/type validation; the layout engine enforces
    the geometry rules (≥2 points, non-degenerate, supported fit/path).
    """

    panel: ComponentRefIn
    post: ComponentRefIn
    path: list[tuple[float, float, float]] = Field(min_length=2)
    closed: bool = False
    fit: Literal["stretch", "tile", "fixed_partial"] = "stretch"
    max_stretch: float = Field(default=0.12, gt=0.0)
    step_rule: Literal["max", "min", "mean"] = "max"

    def to_spec(self) -> FenceSpec:
        return FenceSpec(
            panel=ComponentRef(self.panel.asset_id, self.panel.nominal_width),
            post=ComponentRef(self.post.asset_id, self.post.nominal_width),
            path=tuple(self.path),
            closed=self.closed,
            fit=self.fit,
            max_stretch=self.max_stretch,
            step_rule=self.step_rule,
        )


def _transform_dict(t: Transform) -> dict[str, Any]:
    return {"position": list(t.position), "rotation": list(t.rotation), "scale": list(t.scale)}


def _layout_payload(layout: Any) -> dict[str, Any]:
    """Serialize a :class:`FenceLayout` for the wire."""
    return {
        "posts": [
            {**_transform_dict(p.transform), "kind": p.kind} for p in layout.posts
        ],
        "panels": [
            {
                **_transform_dict(p.transform),
                "bay_length": p.bay_length,
                "stretch": p.stretch,
                "step_height": p.step_height,
            }
            for p in layout.panels
        ],
        "within_tolerance": layout.within_tolerance,
        "counts": {"posts": len(layout.posts), "panels": len(layout.panels)},
    }


# --- WebXR assembly page ---------------------------------------------------


def _render_fence_html(base_id: str, panel_id: str, post_id: str) -> str:
    """Build the three.js + WebXR straight-run fence page.

    Loads the panel + post component GLBs through the existing
    ``/ar/<id>/model.glb`` route, measures each component's width from
    its geometry, and posts tapped start/end points to
    ``/api/fence/layout`` to drive two ``InstancedMesh`` batches.
    """
    safe_base = html.escape(base_id, quote=True)
    safe_three = html.escape(_THREE_VERSION, quote=True)
    panel_js = json.dumps(panel_id)
    post_js = json.dumps(post_id)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Fence AR — {safe_base}</title>
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
            display: flex; flex-direction: column; gap: 8px; font-size: 12px; }}
  #panel .stat {{ display: flex; justify-content: space-between; color: #ddd; }}
  #panel .stat b {{ font-weight: 600; }}
  #panel .warn {{ color: #ffcf6b; }}
  #panel button {{ background: transparent; color: #ddd; border: 1px solid #444;
                   padding: 8px; border-radius: 8px; font-weight: 500; cursor: pointer; }}
  @media (max-width: 480px) {{
    #panel {{ left: 12px; right: 12px; width: auto; }}
    #status {{ bottom: 200px; }}
  }}
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
  <div class="title">Fence AR · {safe_base}</div>
  <a class="back" href="/ar/{safe_base}__panel">← viewer</a>
</div>
<div id="overlay">
  <div id="status">Loading components…</div>
  <div id="panel">
    <div class="stat"><span>Panels</span><b id="n-panels">–</b></div>
    <div class="stat"><span>Posts</span><b id="n-posts">–</b></div>
    <div class="stat" id="fit-row"><span>Fit</span><b id="fit-val">–</b></div>
    <button id="reset-btn" type="button">Reset run</button>
  </div>
</div>
<script type="module">
import * as THREE from 'three';
import {{ ARButton }} from 'three/addons/webxr/ARButton.js';
import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

const PANEL_ID = {panel_js};
const POST_ID = {post_js};
const modelUrlFor = (id) => `/ar/${{id}}/model.glb`;

const statusEl = document.getElementById('status');
const setStatus = (m) => {{ statusEl.textContent = m; }};
const nPanelsEl = document.getElementById('n-panels');
const nPostsEl = document.getElementById('n-posts');
const fitValEl = document.getElementById('fit-val');
const fitRowEl = document.getElementById('fit-row');

const renderer = new THREE.WebGLRenderer({{ alpha: true, antialias: true }});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.xr.enabled = true;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(
  70, window.innerWidth / window.innerHeight, 0.01, 100);
camera.position.set(0, 1.6, 4);

scene.add(new THREE.HemisphereLight(0xffffff, 0xbbbbff, 1.0));
const dir = new THREE.DirectionalLight(0xffffff, 1.0);
dir.position.set(5, 10, 7);
scene.add(dir);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.5, 0);
controls.update();

const reticle = new THREE.Mesh(
  new THREE.RingGeometry(0.07, 0.10, 32).rotateX(-Math.PI / 2),
  new THREE.MeshBasicMaterial({{ color: 0xffffff }})
);
reticle.matrixAutoUpdate = false;
reticle.visible = false;
scene.add(reticle);

// Everything we draw goes in this group so a rebuild is a clean swap.
const fenceGroup = new THREE.Group();
scene.add(fenceGroup);

const loader = new GLTFLoader();
let panelComp = null;  // {{ geom, material, width }}
let postComp = null;

// A loaded GLB may nest its mesh under transformed nodes; bake the
// world matrix into the geometry so per-instance matrices map directly
// from the layout transforms. Our components are single-mesh (one
// material) — take the first mesh and warn if there are more.
function extractComponent(gltf) {{
  gltf.scene.updateWorldMatrix(true, true);
  let mesh = null;
  let count = 0;
  gltf.scene.traverse((o) => {{ if (o.isMesh) {{ count++; if (!mesh) mesh = o; }} }});
  if (!mesh) throw new Error('component GLB has no mesh');
  if (count > 1) console.warn(`component has ${{count}} meshes; instancing the first only`);
  const geom = mesh.geometry.clone();
  geom.applyMatrix4(mesh.matrixWorld);
  geom.computeBoundingBox();
  const size = new THREE.Vector3();
  geom.boundingBox.getSize(size);
  return {{ geom, material: mesh.material, width: size.x }};
}}

function loadComponent(id) {{
  return new Promise((resolve, reject) => {{
    loader.load(modelUrlFor(id), (gltf) => {{
      try {{ resolve(extractComponent(gltf)); }} catch (e) {{ reject(e); }}
    }}, undefined, reject);
  }});
}}

function buildInstanced(comp, placements) {{
  const mesh = new THREE.InstancedMesh(comp.geom, comp.material, placements.length);
  const m = new THREE.Matrix4();
  const pos = new THREE.Vector3();
  const quat = new THREE.Quaternion();
  const scl = new THREE.Vector3();
  placements.forEach((p, i) => {{
    pos.set(p.position[0], p.position[1], p.position[2]);
    quat.set(p.rotation[0], p.rotation[1], p.rotation[2], p.rotation[3]);
    scl.set(p.scale[0], p.scale[1], p.scale[2]);
    m.compose(pos, quat, scl);
    mesh.setMatrixAt(i, m);
  }});
  mesh.instanceMatrix.needsUpdate = true;
  return mesh;
}}

function clearFence() {{
  for (let i = fenceGroup.children.length - 1; i >= 0; i--) {{
    fenceGroup.remove(fenceGroup.children[i]);
  }}
}}

async function fetchLayout(path) {{
  const spec = {{
    panel: {{ asset_id: PANEL_ID, nominal_width: panelComp.width }},
    post: {{ asset_id: POST_ID, nominal_width: postComp.width }},
    path,
    closed: false,
    fit: 'stretch',
  }};
  const r = await fetch('/api/fence/layout', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(spec),
  }});
  if (!r.ok) throw new Error('layout failed: HTTP ' + r.status);
  return r.json();
}}

// Posts come back already deduped (a straight run of N panels has
// exactly N+1 posts — the shared boundary posts are single entries),
// so instancing layout.posts directly never double-counts a post.
function rebuild(layout) {{
  clearFence();
  fenceGroup.add(buildInstanced(postComp, layout.posts));
  fenceGroup.add(buildInstanced(panelComp, layout.panels));
  nPanelsEl.textContent = layout.counts.panels;
  nPostsEl.textContent = layout.counts.posts;
  fitValEl.textContent = layout.within_tolerance ? 'ok' : 'stretched';
  fitRowEl.classList.toggle('warn', !layout.within_tolerance);
}}

async function layoutRun(a, b) {{
  try {{
    const layout = await fetchLayout([a, b]);
    rebuild(layout);
    const warn = layout.within_tolerance ? '' : ' (panels stretched > tolerance)';
    setStatus(`${{layout.counts.panels}} panels · ${{layout.counts.posts}} posts${{warn}}`);
  }} catch (e) {{
    setStatus('Layout error: ' + (e.message || e));
  }}
}}

Promise.all([loadComponent(PANEL_ID), loadComponent(POST_ID)])
  .then(([panel, post]) => {{
    panelComp = panel;
    postComp = post;
    // Desktop preview: a default flat 3-bay run so the page is useful
    // without a phone. AR taps replace it.
    const span = panelComp.width * 3;
    return layoutRun([0, 0, 0], [span, 0, 0]).then(() => {{
      controls.target.set(span / 2, 0.4, 0);
      controls.update();
      setStatus('Preview run. Tap "START AR", then tap start + end on a surface.');
    }});
  }})
  .catch((e) => setStatus('Failed to load components: ' + (e.message || e)));

const resetBtn = document.getElementById('reset-btn');
resetBtn.addEventListener('click', () => {{
  clearFence();
  startPoint = null;
  nPanelsEl.textContent = nPostsEl.textContent = '–';
  fitValEl.textContent = '–';
  fitRowEl.classList.remove('warn');
  setStatus('Run cleared. Tap start + end on a surface.');
}});

const arButton = ARButton.createButton(renderer, {{
  requiredFeatures: ['hit-test'],
  optionalFeatures: ['dom-overlay'],
  domOverlay: {{ root: document.getElementById('overlay') }}
}});
arButton.classList.add('xr-button');
document.body.appendChild(arButton);

let hitTestSource = null;
let localSpace = null;
let startPoint = null;

renderer.xr.addEventListener('sessionstart', async () => {{
  clearFence();
  startPoint = null;
  setStatus('Find a surface, then tap the START of the fence.');
  const session = renderer.xr.getSession();
  const viewerSpace = await session.requestReferenceSpace('viewer');
  hitTestSource = await session.requestHitTestSource({{ space: viewerSpace }});
  localSpace = await session.requestReferenceSpace('local');
}});

renderer.xr.addEventListener('sessionend', () => {{
  hitTestSource = null;
  localSpace = null;
  reticle.visible = false;
  startPoint = null;
}});

const controller = renderer.xr.getController(0);
controller.addEventListener('select', () => {{
  if (!reticle.visible || !panelComp || !postComp) return;
  const p = new THREE.Vector3().setFromMatrixPosition(reticle.matrix);
  if (!startPoint) {{
    startPoint = [p.x, p.y, p.z];
    setStatus('Start set. Tap the END of the fence.');
  }} else {{
    layoutRun(startPoint, [p.x, p.y, p.z]);
    startPoint = null;  // next tap starts a fresh run
  }}
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


def build_fence_router(store: ARStore) -> APIRouter:
    """Construct the fence router with ``store`` baked in.

    Mirrors :func:`build_ar_router` — a fresh router per call keeps
    tests isolated.
    """
    router = APIRouter(tags=["fence"])

    @router.post("/api/fence/layout")
    async def fence_layout(spec_in: FenceSpecIn) -> dict[str, Any]:
        """Compute a fence layout from a ``FenceSpec``.

        Thin wrapper over :func:`compute_fence_layout`. Geometry errors
        (too few points, degenerate segment, bad width) map to 400;
        unsupported-but-valid requests (polylines, closed loops, other
        fit modes) map to 501 since they're a later phase, not a client
        mistake.
        """
        try:
            layout = compute_fence_layout(spec_in.to_spec())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        _log.info(
            "fence.layout posts=%d panels=%d in_tol=%s",
            len(layout.posts), len(layout.panels), layout.within_tolerance,
        )
        return _layout_payload(layout)

    @router.get("/ar/{base_id}/fence", response_class=HTMLResponse)
    async def fence_page(base_id: SceneId) -> HTMLResponse:
        """Return the WebXR straight-run assembly page for ``base_id``.

        Requires both ``<base>__panel`` and ``<base>__post`` components
        to exist (built by Phase 8.B); 404 otherwise so we fail before
        serving a page whose GLB fetches would 404.
        """
        panel_id = panel_component_id(base_id)
        post_id = post_component_id(base_id)
        if not (store.exists(panel_id) and store.exists(post_id)):
            _log.info("fence.page status=404 base=%s", base_id)
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Fence components not found for {base_id!r}; "
                    f"expected {panel_id} and {post_id}."
                ),
            )
        _log.info("fence.page status=200 base=%s", base_id)
        return HTMLResponse(_render_fence_html(base_id, panel_id, post_id))

    return router
