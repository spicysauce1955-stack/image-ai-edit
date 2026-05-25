# Multi-section fence — kit-of-parts + runtime assembly (research)

**Date:** 2026-05-25. Feeds Phase 8 in `docs/ar-plan.md`. Two streams:
how modular fences are built procedurally (game/CAD), and how to
assemble repeated components at runtime in WebXR/three.js.

---

## The core rule (fencepost / off-by-one)

A fence is **panels separated by shared posts**:
- Straight open run: **posts = panels + 1**
- Closed loop: **posts = panels**
- Pickets per panel: `ceil(panelWidth / (picketWidth + gap))`.

Instancing a full "section" (panel + 2 posts) N times is **wrong** — it
double-counts the shared boundary posts. Every surveyed tool decomposes
into a **kit of parts**: place POSTS at boundaries, PANELS between them.

This is the same model as the repo's existing 2D pole-based builder
(place poles, sections auto-generate between consecutive poles).

---

## How the tools do it (all converge on the same pattern)

| Tool | Pattern |
|---|---|
| **Unreal** | Spline + Instanced Static Mesh (ISM) for posts; ISM or `USplineMeshComponent` for panels; PCG "Fence Generator" graph places instances along a spline |
| **Unity** | Splines package (length/point sampling) + GPU instancing; spline-mesher plugins tile/stretch a panel mesh between sampled points |
| **Blender** | Geometry Nodes: Mesh Line/Curve + **Instance on Points** for posts, panels instanced/stretched between; orient to curve tangent |
| **Houdini** | `Resample` SOP to set bay length + spawn post points; `copy to points` for posts & panels; custom corner geometry |

Common thread: **sample the path → post points at boundaries → instance posts → instance/stretch panels between adjacent posts.**

---

## The layout algorithm (synthesized)

User params: `panelWidth W`, `roundingMethod ∈ {floor,ceil,round}`,
`allowVariableLastPanel`, `maxStretchPct`, `slopeMode ∈ {stepped,racked}`,
`closed`.

```
L = path length
panels = round(L / W)            # rounding policy; ceil is the common default
bayLength = L / panels           # uniform; or fixed W with a variable last panel
for i in 0..panels:              # POSTS — one per boundary (shared)
    d = i * bayLength
    postPos[i]     = path.locationAtDistance(d)
    postTangent[i] = path.tangentAtDistance(d)
for i in 0..panels-1:            # PANELS — between adjacent posts
    a, b   = postPos[i], postPos[i+1]
    center = (a+b)/2
    rot    = lookRotation(b-a, up)        # align to segment (or tangent if racked)
    scaleX = dist(a,b) / basePanelWidth   # stretch to fit (clamp to maxStretchPct)
posts = panels + 1               # open run; posts = panels for closed loop
```

- **Corners** (polyline vertices): place a dedicated **corner post** at the
  junction; panels meet at the angle. Optionally miter rails
  (`α = arctan(n·sinθ / (m + n·cosθ))`). Closed loop: post 0 == post N.
- **Slope**: *stepped* (panels stay flat/level, posts step down the grade)
  vs *racked/raked* (panels rotate to follow the grade via tangent + roll).
- **End vs line vs corner posts** can be distinct post variants.

---

## Decomposition: getting the PANEL + POST components

1. **Generate separately (recommended for us)** — feed the image→3D
   pipeline a *panel-only* crop (posts masked out) → panel GLB, and a
   *post-only* crop → post GLB. Reuses the multi-view-prep machinery
   (`scripts/poc_fence_3d.py` already isolates the panel).
2. **Part-splitting** — Hunyuan3D 3.1 has a part-split post-process
   endpoint (~$0.45/gen, per the image-to-3d research); the
   part→panel/post mapping isn't guaranteed and the exact API wasn't
   re-confirmable in this round.
3. **Mesh segmentation** — split a section GLB by connected components /
   bounding box (posts at x-extremes, panel in the middle). Cheap, no
   API, but fragile.

Economics: 2 component generations → **any length assembles for free**
(no per-length 3D generation).

---

## Runtime assembly in WebXR / three.js

- **`THREE.InstancedMesh`**: load a component GLB once, draw N copies via
  per-instance matrices (`setMatrixAt` + a dummy `Object3D`;
  `DynamicDrawUsage` if matrices change). One instanced batch per
  unique geometry+material (one for posts, one for panels).
- **Shared-post dedup**: index post positions by endpoint coordinate;
  emit one instance per *unique* boundary → shared posts are a single
  instance automatically.
- **Path definition**: WebXR hit-test to sample ground poses → polyline
  → **RDP simplify** → optional Catmull-Rom smooth → **quantize** into
  panel-width segments.
- **Seam snapping**: `geometry.computeBoundingBox()` on each component;
  align by bounding-box anchors; snap shared endpoints within a
  tolerance.
- **Perf**: instancing cuts draw calls when many identical parts share a
  material, but frustum-culling differs and on weak mobile GPUs a few
  hundred individual draws can rival a big instanced batch — measure on
  device. `BufferGeometryUtils.mergeGeometries` is the alternative for
  static runs.
- **`EXT_mesh_gpu_instancing`** (glTF): encodes per-instance TRS in the
  file; Babylon supports it, three.js/model-viewer support is evolving,
  Blender doesn't export it by default; `glTF-Transform` can add it at
  build time. **Support is fragmented** — for our `/live` page (bare
  GLTFLoader) we'll assemble live with `InstancedMesh` objects, no glTF
  extension, so it stays portable.

---

## Implications for our project

- **Runtime three.js assembly** is the natural AR path (user defines the
  ground path; we instance posts+panels). Stays extension-free →
  compatible with our existing bare-GLTFLoader `/live` page.
- **Bake-to-GLB** option (merge instances into one extension-free GLB via
  the `optimize_glb` / gltf-transform tooling we already have) for
  model-viewer / iOS Quick Look / sharing, which can't assemble at
  runtime.
- The **layout algorithm is a pure function** — testable with zero AR /
  network, so it's the safe first deliverable.

---

## Addendum — real fencing standards + assembly mechanics (deeper pass)

**Domain standards** (ground the data model):
- Panel widths: commonly **6 ft / 8 ft**; post spacing "on-center" by
  system (wood 6–8 ft, vinyl = panel width, chain-link 8–10 ft).
- **Post types matter**: line (field), terminal/end, corner, gate,
  brace — different geometry + footing. Model carries a `kind`.
- Rails ≈ 1 per 24" height (6 ft privacy = 3 rails); pickets =
  `ceil(width/(picket+gap))`.
- **Slope**: *stepped* (panels stay rectangular, step down) vs *racked*
  (parallelogram, pickets plumb + rails follow grade; vinyl racks ~10°).
- **Units**: real fencing is imperial inches; glTF/WebXR is metres,
  +Y up, +Z forward → store metres, treat imperial as display.

**Assembly mechanics** (refines the naive "stretch" idea):
- **Don't uniform-stretch the whole panel** — it distorts pickets + UVs.
  Prefer tiling the infill or fixed-width + trimmed last bay; allow only
  small uniform stretch (physical installs keep mismatch **< ~10%**).
  Our `round()`-based bay count self-limits stretch to ~±10%, so the
  v1 `stretch` fit is acceptable with a single baked panel GLB.
- **Component anchors**: place the panel origin at a logical attach point
  (base, mid-width), name anchor nodes + write `node.extras`
  (`nominalWidth`, role) — exporters preserve `node.extras`. glTF is
  +Y up / +Z forward / metres.
- **Instancing** for rigid panels (cheap); spline-deform only when
  bending (racked). Tile textures / repeat geometry rather than scaling
  to preserve slat aspect.
- **Corner / transform math was a research gap** → derived in
  `docs/multi-section-fence-design.md` §6 (look-rotation between two
  posts, corner-post bisector, miter `90°−θ/2`, racked shear).

**The full solution design** built on all of this lives at
`docs/multi-section-fence-design.md`.

## Sources

Domain standards (deeper pass):
- Fence post spacing — https://nmifence.com/blog/fence-post-spacing ; https://buyafence.com/fence-post-spacing-calculator-how-far-apart-should-fence-posts-be
- Post types — https://starpickets.com/technology/different-types-of-fence-posts.html
- Bufftech vinyl install (slope/step/rack) — https://bufftech.com/wp-content/uploads/sites/2/2023/10/bufftech-install-guide-e-2201cts.pdf
- Slope (stepped vs racked) — https://avinylfence.com/vinyl-fence-installation-on-slope ; https://graberoutdoors.com/fencing-a-sloped-yard-what-you-need-to-know
- ASTM F567 chain-link practice — https://spsfence.com/resources/ASTM/ASTM-F567.pdf
- Ornamental steel catalog (tolerances, racking) — https://masterhalco.com/hubfs/MH%20PDF%20Files/Ornamental-Steel-Downloads/Montage-Ornamental-Steel/Catalog/Montage-Plus-Catalog.pdf

Assembly mechanics (deeper pass):
- Unreal SplineMesh vs ISM — https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/USplineMeshComponent ; https://dev.epicgames.com/documentation/unreal-engine/instanced-static-mesh-component-in-unreal-engine
- Blender resample curve — https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/curve/operations/resample_curve.html
- Blender glTF extras / anchors — https://docs.blender.org/manual/en/latest/addons/import_export/scene_gltf2.html
- glTF 2.0 spec (axes/units/extras) — https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html
- three.js scene optimization / instancing — https://tympanus.net/codrops/2025/02/11/building-efficient-three-js-scenes-optimize-performance-while-maintaining-quality
- Panel module mismatch tolerance — https://recgroup.com/sites/default/files/documents/module_mismatch_en.pdf

Kit-of-parts / procedural:
- Unreal spline + meshes — https://dev.epicgames.com/community/learning/tutorials/39/unreal-engine-populating-meshes-along-a-spline-with-blueprints
- Unreal PCG Fence Generator — https://dev.epicgames.com/documentation/unreal-engine/creating-a-fence-generator-using-shape-grammar-in-unreal-engine
- Unreal USplineMeshComponent — https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/USplineMeshComponent
- Unity Splines — https://docs.unity3d.com/Packages/com.unity.splines@2.4/manual/index.html
- Unity GPU Instancing — https://docs.unity3d.com/Manual/GPUInstancing.html
- Blender Geometry Nodes fence — https://80.lv/articles/tutorial-making-dynamic-fence-using-blender-s-geometry-nodes
- Houdini fence (Project Titan) — https://sidefx.com/tutorials/project-titan-fence-tool
- Fence material/post-count calculators — https://omnicalculator.com/construction/fence-material ; https://nationalcalculatorauthority.com/fence-panel-and-picket-count-calculator
- Miter angle — https://omnicalculator.com/construction/miter-angle

Runtime assembly / instancing:
- three.js InstancedMesh w/ GLB — https://discourse.threejs.org/t/how-can-i-get-instancedmesh-working-properly-with-glb/40623
- three.js BufferGeometryUtils.mergeGeometries — https://threejs.org/docs/pages/module-BufferGeometryUtils.html
- EXT_mesh_gpu_instancing — https://github.com/KhronosGroup/glTF/blob/main/extensions/2.0/Vendor/EXT_mesh_gpu_instancing/README.md
- glTF-Transform EXTMeshGPUInstancing — https://gltf-transform.dev/modules/extensions/classes/EXTMeshGPUInstancing
- WebXR hit-test — https://developer.mozilla.org/en-US/docs/Web/API/XRSession/requestHitTestSource ; https://immersive-web.github.io/hit-test/hit-testing-explainer.html
- WebXR anchors — https://developer.mozilla.org/en-US/docs/Web/API/XRAnchor
