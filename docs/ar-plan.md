---
created: 2026-05-18
updated: 2026-05-19
tags: [project, task, ar]
---

# AR plan — WebAR-first, modular, extendable

> **2026-05-19 replan:** AI image→3D generation is deferred. Phase 2
> becomes a **curated asset catalog** sourced from free 3D models on
> the web (Khronos, Apple AR Quick Look gallery, Poly Haven, Kenney).
> The `Scene3DModel` / `Format3DConverter` ABCs from Phase 0 stay in
> place as Phase 5 hooks for when AI generation is reopened.

## Goal

Extend the 2D insertion pipeline with an AR delivery surface so a user can preview the inserted object **in their own space** through a phone or browser. The first ship is **`<model-viewer>` over the existing FastAPI server**: zero native code, works on every modern phone (iOS Quick Look + Android Scene Viewer + WebXR-capable browsers).

This plan extends `poc-plan.md` (which proved the 2D pipeline). It does **not** replace it — the 2D composite remains the primary output; AR is the second surface.

Background research that informs every choice here: `research/INDEX.md` (and especially `research/ar-survey/06-synthesis/index.md`).

## Constraints / shape

- **General**: AR capability is object-agnostic. Fences are one use case among many.
- **Modular**: AR is added as new capability ABCs (`Scene3DModel`, `Format3DConverter`) and providers, following the same adapter pattern as `EditModel` / `SegmentationModel`. The AR delivery layer (Phase 1) is independent of generation (Phase 2).
- **Extendable**: nothing in Phases 0–4 forecloses future work on SLAM-anchored WebXR, AR Foundation native builds, or Gaussian Splatting pipelines. Phase 5 leaves interface hooks for those without implementing them.
- **Professional**: every phase ends with a passing test. CI smoke runs on every PR by Phase 4.
- **Small steps**: each phase below is a single well-defined unit of work. Don't merge a partial phase.

## Out of scope for this plan

- World-tracked SLAM that persists virtual objects across app launches. (Future workstream — see Phase 5 note.)
- Native iOS/Android apps. (Same.)
- AR multiplayer / shared anchors. (Same.)
- Self-hosted model weights for image→3D. (Match the repo's existing "hosted APIs only" rule from `stack-decision.md`.)

## Success criteria

A reviewer on their phone, given a URL like `https://localhost:8000/ar/<scene_id>`:

1. Opens the page; sees an interactive 3D preview rotate-able by drag.
2. Taps "View in your space"; OS native viewer (Quick Look on iOS, Scene Viewer on Android) launches.
3. Drops the object into the camera view; can resize/rotate; output is photorealistic at fence/yard-object scale.
4. Closes the viewer, returns to web page.

If 1–2 work but 3 fails (object scale or quality), iterate the asset pipeline in Phase 4. If 1 fails, the viewer/asset is broken — fix Phase 1 or Phase 2.

## Phases

Each phase is a single PR, ends green on tests.

### Phase 0 — Shape (no AI, no AR delivery yet)
- [ ] `Scene3DAsset`, `Scene3DResponse` dataclasses on `models/base.py`
- [ ] `Scene3DModel` capability ABC (text + optional reference images → asset)
- [ ] `Format3DConverter` capability ABC (asset + target format → asset)
- [ ] Re-export from `models/__init__.py`
- [ ] `tests/` directory + pytest config in `pyproject.toml`
- [ ] Tests cover the dataclasses (find-by-mime, edge cases) and verify the ABCs can be subclassed

### Phase 1 — Static AR delivery (BYO asset)
- [ ] `GET /ar/{scene_id}` returns a tiny HTML page wired with `<model-viewer>` and the right iOS/Android handoff attrs
- [ ] `GET /ar/{scene_id}/model.glb`, `GET /ar/{scene_id}/model.usdz` serve the assets with correct MIME (`model/gltf-binary`, `model/vnd.usdz+zip`)
- [ ] Asset storage abstraction in `pipeline/ar_store.py` (filesystem-backed first; swappable later)
- [ ] Seed `out/scenes/` with one Khronos sample GLB+USDZ pair so the route is testable without any generator
- [ ] Tests: HTML contains `<model-viewer>` with both `src=` and `ios-src=`; both asset routes return the right MIME and bytes
- [ ] Manual smoke checklist in `docs/runbook.md`: iPhone Quick Look + Android Scene Viewer

### Phase 2 — Curated asset catalog (replaces "image→3D provider")

**Replan note (2026-05-19):** AI generation is deferred. We use existing
free 3D models from trustworthy sources (Khronos Sample Assets, Apple
AR Quick Look gallery, Poly Haven, Kenney, Quaternius). The catalog
becomes the user-facing surface; the `Scene3DModel` ABC remains in
place as a future hook (Phase 5).

- [ ] `pipeline/asset_catalog.py`: `AssetCatalogEntry` dataclass +
  `AssetCatalog` reader, both loading from a single JSON manifest
- [ ] `assets/catalog.json`: curated entries with `id`, `name`,
  `category`, `glb_url`, `usdz_url` (nullable), `thumbnail_url`,
  `license`, `attribution`, `source_url`, optional `scale_hint`
- [ ] Seed initial entries (≥ 6): Khronos Box / Duck / DamagedHelmet for
  sanity, plus 3+ yard-relevant CC0 assets (fence panel, planter, shed
  or similar)
- [ ] `scripts/fetch_catalog.py [--id ID ...] [--all]`: downloads
  catalog entries into the AR store, replacing the one-off
  `fetch_ar_demo.py` (which becomes a thin shim or is removed)
- [ ] Tests: catalog JSON loads, lookup by id, filter by category,
  manifest schema validation. Mock httpx for download tests.

### Phase 3 — Catalog API + UI integration

- [ ] `GET /api/catalog` returns the list of catalog entries (no asset
  bytes — just metadata + URLs the client can follow)
- [ ] `GET /api/catalog/{asset_id}` returns one entry
- [ ] Web UI: a `/catalog` page lists available models with thumbnail
  + "View in AR" link → `/ar/<asset_id>`
- [ ] Web UI: on the main upload page, after generating a 2D composite,
  show a "Try in AR" picker constrained to entries whose `category`
  matches a heuristic from the user's instruction (e.g. instruction
  contains "fence" → show only fences)
- [ ] Tests: route returns the expected JSON shape; picker heuristic
  works for fence / shed / pool labels.

### Phase 4 — Quality + observability

- [ ] `scripts/fetch_catalog.py` runs a glTF validator (Khronos
  `gltf-validator` via npm or a Python wrapper) on every downloaded
  GLB; fail-closed entries are flagged in the manifest as `broken: true`
  and skipped by the route layer
- [ ] Optional: post-process big GLBs with `gltfpack` (meshopt) +
  KTX2 textures. Only run when the source GLB is > 5 MB
- [ ] Structured logs around AR delivery: request counts, 404s, asset
  bytes served, cache hit/miss when we add caching
- [ ] CI smoke: AR routes return the expected MIMEs for the seeded
  Box entry; catalog endpoint returns ≥ 1 entry

### Phase 5 — Hooks (interfaces only, do not implement)

- [ ] `Scene3DModel` ABC remains; document in `docs/architecture.md`
  how a generator (Meshy / Trellis / Rodin / SPAR3D) would slot in as
  a "catalog of one" — same `ARStore`, just populated on demand
- [ ] `Format3DConverter` ABC remains; document GLB→USDZ paths
  (`usdzconvert`, fal.ai endpoint) for when a catalog entry lacks a
  pre-built USDZ
- [ ] `MeshFromSegmentation` and `GaussianSplatModel` stubs for the
  longer-term roadmap (SAM + depth → mesh; Luma/Polycam input)
- [ ] Migration note on the WebXR-SLAM / AR Foundation native track

### Phase 6 — Realtime in-browser AR placement

**2026-05-19 replan:** the original plan stopped at OS-delegated AR
(Quick Look / Scene Viewer handoff). The user goal is realtime
placement *inside the app context* — tap a surface, see a model
anchored there, walk around it, compose multiple objects, eventually
bridge back to the 2D pipeline. Path: WebXR-direct via three.js, on
top of the existing catalog + AR routes. iOS Safari WebXR is still
limited (research/ar-survey/01-web-ar/findings.md, "WebXR Device API
support matrix"), so iOS users keep the existing Quick Look fallback
— Phase 6 is additive, not replacement.

Why WebXR over native: keeps the Python + web stack consistent with
`docs/stack-decision.md`; the synthesis doc's "Web AR" path is the
cheapest route to realtime hit-test placement and avoids forking
into Unity / AR Foundation builds. See `research/ar-survey/06-synthesis/index.md`.

- **6.A — three.js + WebXR scaffold** ✓ each phase: one PR, ends green
  - [ ] `GET /ar/{scene_id}/live` returns a three.js page wired with
    WebXR `immersive-ar` + `hit-test`. ARButton handles entry +
    no-support fallback.
  - [ ] Tap a detected surface → place the catalog entry's model. One
    instance at a time (6.B adds manipulation).
  - [ ] Link from `/ar/{scene_id}` viewer page (where WebXR is
    likely) to the `/live` variant.
  - [ ] Tests: route returns HTML, references three.js + the GLB
    URL; 404 for unknown scenes; scene-id regex still blocks
    traversal.

- **6.B — Touch manipulation**
  - [ ] Drag-on-plane to move, two-finger rotate, pinch to scale.
  - [ ] "Lock" button to commit a placement; "Reset" to clear.
  - [ ] DOM overlay for the manipulation HUD.

- **6.C — Multi-object composition**
  - [ ] In-AR catalog drawer (small list of thumbnails) opened from
    a button on the HUD.
  - [ ] Tap entry → place another instance.
  - [ ] Per-instance selection + transform.
  - [ ] "Snapshot" → captures camera + virtual overlay to a PNG and
    POSTs it to a new server endpoint that returns a download URL.

- **6.D — Bridge to the 2D pipeline**
  - [ ] "Photoreal it" button on the snapshot panel: hand the AR
    screenshot to the existing `pipeline/insert.py` with the placed
    model as the reference, producing a photoreal 2D composite.
  - [ ] Closes the AR-to-2D loop and lets the same catalog drive
    both surfaces.

- **6.E — Persistence (optional, can split off)**
  - [ ] Local: localStorage-backed placement save / restore keyed by
    `scene_id`.
  - [ ] Cloud (much later): a stored anchor backend + a VPS provider
    integration (Niantic Lightship / Immersal). Research synthesis
    has the comparison.

## Repo layout (target after Phase 3)

```
image-ai-edit/
├── assets/
│   └── catalog.json                          # NEW (Phase 2) — curated 3D model manifest
├── docs/
│   └── ar-plan.md                            # this file
├── src/ai_edit/
│   ├── models/base.py                        # Scene3DAsset, Scene3DResponse, Scene3DModel, Format3DConverter
│   ├── pipeline/
│   │   ├── asset_catalog.py                  # NEW (Phase 2)
│   │   └── ar_store.py                       # Phase 1
│   └── server/
│       ├── app.py                            # + /api/catalog routes (Phase 3)
│       ├── ar_routes.py                      # Phase 1
│       └── static/catalog.html               # NEW (Phase 3) — model picker UI
├── scripts/
│   ├── fetch_ar_demo.py                      # Phase 1 (kept for one-line smoke)
│   └── fetch_catalog.py                      # NEW (Phase 2) — populates store from catalog.json
├── tests/
│   ├── pipeline/test_asset_catalog.py        # NEW (Phase 2)
│   └── server/test_catalog_routes.py         # NEW (Phase 3)
└── out/
    └── scenes/<asset_id>/{model.glb,model.usdz}
```

## Open decisions before Phase 2

- **Catalog sourcing**: Khronos Sample Assets (CC-BY / CC0, certified),
  Apple AR Quick Look gallery (pre-built USDZ, no GLB — license per
  page), Poly Haven (CC0), Kenney.nl + Quaternius (CC0 game assets).
  Need at least 3 yard-relevant items to be useful for the existing
  fence/yard use case. Plan: I'll propose specific URLs before
  downloading anything.
- **Catalog persistence**: `assets/catalog.json` checked into git
  (single source of truth). Downloads land in `out/scenes/`. Object
  storage upgrade still future Phase 4+.
- **USDZ coverage**: Apple gallery entries ship pre-built USDZ; Khronos
  / Poly Haven don't. Either (a) accept iOS Quick Look gap for those
  entries (current behaviour), or (b) add `Format3DConverter` impl in
  Phase 4 to fill the gap. Default: (a) until users complain.

## Risks

- Free yard-object models are rarer than generic samples. Mitigation:
  start with what's available; track unmet categories; consider AI
  generation as the answer for those gaps later (re-opens the door we
  parked in this replan).
- License attribution drift — model authors expect credit per CC-BY.
  Mitigation: catalog manifest carries `attribution` and `source_url`;
  the UI surfaces them on the AR page.
- Stale upstream URLs (Khronos repo moves, Apple gallery URLs shift).
  Mitigation: glTF validator runs on every fetch; `fetch_catalog.py`
  surfaces failures clearly.
- `<model-viewer>` AR button does not appear if device fails capability
  detection — common cause is wrong MIME or missing `ios-src`.
  Mitigation: explicit MIME tests in Phase 1 (already done); manual
  phone smoke in runbook.

## Phase 7 — Generative multi-image → 3D

**2026-05-25:** realizes the `Scene3DModel` AI-gen hook reserved in
Phase 5. Turns photos (ideally 3–4 angles of one object) into a GLB
that lands in the `ARStore` and serves through the existing AR routes.
Grounded in `research/image-to-3d/` (esp. `synthesis.md`).

**Scope of the first cut (deliberately small):**
- Generative *sparse multi-view* (not photogrammetry).
- Output **GLB only**, textured PBR as the model emits it — renders in
  color via `<model-viewer>` + Scene Viewer. USDZ + color-fidelity
  hardening are deferred to `Format3DConverter` (not this phase; see
  `research/image-to-3d/synthesis.md` → color/material note).
- Provider: **fal.ai-hosted**, reusing `FAL_KEY` + the queue/subscribe
  client already in `providers/falai.py`.

The `Scene3DModel.generate(prompt, references=[...], ...)` ABC is
already multi-image-ready (`references` is a list), so this is one
provider class + thin wiring, not a redesign.

### 7.0 — Spike: confirm the fal endpoint (no commit beyond a doc note)
- [ ] Confirm exact model + params on the live fal page: Hunyuan3D 3.1
  (up to 8 views, PBR) vs TRELLIS `/multi`. Capture field names (image
  array vs named slots), max views, per-gen cost, commercial-license
  text. Record the choice in `docs/stack-decision.md`.

### 7.A — `FalAIMultiImageTo3D` provider
- [ ] New handler class in `providers/falai.py` implementing
  `Scene3DModel`: takes `prompt` + `references: list[(bytes, mime)]`,
  data-URI-uploads them, `fal_client.subscribe`, downloads the GLB,
  returns a `Scene3DResponse` (GLB asset).
- [ ] Re-use existing `_data_uri` / `_download` helpers.
- [ ] Tests: mocked `fal_client.subscribe` for unit; one
  `@pytest.mark.network` integration test gated by `RUN_NETWORK_TESTS=1`
  asserting a valid GLB comes back (reuse `validate_glb`).

### 7.B — CLI: `scripts/poc_3d.py`
- [ ] `poc_3d.py --prompt "a wooden planter" img1.jpg img2.jpg img3.jpg`
  → calls the provider, runs `validate_glb`, writes
  `out/scenes/<id>/model.glb` (mirrors `catalog_fetch` store usage).
- [ ] Prints the `/ar/<id>` and `/ar/<id>/live` URLs to view it.
- [ ] Manual quality pass: same 3–4 photos through the chosen model;
  eyeball in the live viewer. (Optionally A/B vs Meshy later.)

### 7.C — Server endpoint
- [ ] `POST /api/generate3d` — multipart (N images + prompt). Runs the
  provider, validates, stores under a fresh `scene_id`, returns
  `{scene_id, ar_url, live_url}`.
- [ ] Latency is ~20–40 s+, so model it as a background job: return a
  job id immediately, poll `GET /api/generate3d/{job}` for status →
  scene URLs. (Reuse the in-memory job pattern from the existing
  result cache in `server/app.py`.)
- [ ] Upload limits + image validation reuse the Phase-hardening helpers
  already in `server/app.py`.
- [ ] Tests: route with an injected fake `Scene3DModel` (no network).

### 7.D — UI: "Generate 3D from photos"
- [ ] Minimal multi-image dropzone (1–4 photos) + prompt field that
  POSTs to `/api/generate3d`, polls, then surfaces "View in AR" /
  "Live AR" links. Reuses the catalog/AR-picker styling.
- [ ] Static-wiring test like `test_index_ui_wiring.py`.

**Open decisions to confirm before 7.A:**
1. **Model:** Hunyuan3D 3.1 (more views, PBR, ~$0.375+/gen) vs TRELLIS
   `/multi` (simpler/cheaper). Default: Hunyuan3D 3.1.
2. **Endpoint UX:** background job (recommended, given latency) vs
   sync-wait. Default: background job.
3. **Cost guard:** cap generations / require explicit opt-in, since each
   call costs real money.

## Phase 8 — Multi-section fences (kit-of-parts assembly)

**2026-05-25.** Build a fence of *combined* sections in AR. The defining
constraint: sections share posts — N panels on a straight run need
**N+1 posts**, not 2N (closed loop: N posts). So we assemble from
reusable PANEL + POST components, not by repeating a whole "section".
The 3D analog of the repo's existing 2D pole-based builder.

> **Full solution design: [`multi-section-fence-design.md`](./multi-section-fence-design.md)**
> — data model, layout algorithm + transform math, component conventions,
> runtime + bake assembly, API, UX, testing, and acceptance criteria.
> Research + sources: `research/multi-section-fence/findings.md`.
> The summary below is the at-a-glance; the design doc is authoritative.

### Hard constraint: keep existing features intact

Everything shipped works and must keep working. Phase 8 is **purely
additive** — new modules, new routes, new scripts. Do NOT modify:
- the 2D pipeline (`pipeline/insert.py`, the `/api/insert` route, the
  pole/polygon/overlay handling),
- the AR delivery routes (`/ar/{id}`, `/ar/{id}/live`, `/catalog`,
  `/api/catalog`),
- the image→3D provider (`FalAIMultiImageTo3D`), `ARStore`,
  `asset_validate`, `optimize_glb`, the catalog.
Reuse these; don't change them. The existing 189 tests must stay green;
Phase 8 only adds tests.

### Data model (new, additive)

`pipeline/fence.py`:
- `FenceSpec` (frozen dataclass): `panel_asset_id`, `post_asset_id`,
  `panel_width`, `post_width`, `path` (list of points), `closed: bool`,
  `slope_mode` ("stepped"|"racked", default "stepped"), rounding policy.
- `compute_fence_layout(path, panel_width, *, closed, ...) -> FenceLayout`
  — **pure function**, no rendering/network. Returns `posts: list[Transform]`
  (deduped, shared at boundaries) and `panels: list[Transform]`
  (position/rotation/scale-x). Encodes posts=panels+1 (open) / =panels
  (closed), corner posts at polyline vertices, last-panel stretch.
  This is the testable heart of the feature and the **first deliverable**.

The `path` concept is intentionally the same as the 2D builder's poles.
We will NOT touch the 2D code, but `FenceSpec` is designed so a future
adapter can build it from those poles (one fence model, two surfaces) —
deferred, noted only.

### Component sourcing (decision: generate separately)

Extend the image→3D prep (do NOT change the single-section path) to emit
two components from a source image: a **panel-only** GLB (posts masked
out) and a **post-only** GLB. Reuses `poc_fence_3d.py`'s isolate step +
`FalAIMultiImageTo3D` + `optimize_glb`. Stored in `ARStore` under
component ids (e.g. `<fence>__panel`, `<fence>__post`). Part-splitting
and mesh-segmentation are documented alternatives, not the v1 path.

### Assembly (decision: runtime three.js, plus optional bake)

- **Primary — runtime in a new WebXR page** (`/ar/{id}/fence` or a flag
  on the live page): load PANEL + POST component GLBs, define the ground
  path via WebXR hit-test, run the layout, place `THREE.InstancedMesh`
  batches (one for posts, one for panels), dedup shared posts. Stays
  extension-free → compatible with the bare GLTFLoader. New page; the
  existing `/live` is untouched.
- **Secondary — bake to one GLB** (`scripts/bake_fence.py` / an API
  route) for model-viewer / iOS Quick Look / sharing, since those can't
  assemble at runtime. Merge via the existing `optimize_glb` /
  gltf-transform tooling; keep extension-free.

### Sub-phases (each a small, tested, committed PR)

- **8.A — Layout engine.** `pipeline/fence.py`: `FenceSpec` +
  `compute_fence_layout`. Pure Python, no deps beyond stdlib/numpy.
  Heavy unit tests: post counts (open N+1, closed N), shared-post dedup,
  last-panel stretch, corner posts at vertices, degenerate paths. No AR,
  no network. **Start here.**
- **8.B — Components.** A prep step/script that emits panel-only +
  post-only GLBs from an image, stored as components. Reuses existing
  isolate + provider + optimizer. Mocked tests; one gated live test.
- **8.C — Straight-run AR assembly.** New WebXR page: tap start→end (or
  drop 2 posts), auto-fill panels, shared posts, InstancedMesh. The
  layout algorithm ported to JS (or fetched from a Python
  `/api/fence/layout` endpoint that wraps the 8.A pure function — keeps
  one source of truth). Static-wiring tests.
- **8.D — Polyline + corners.** Multi-segment paths, corner posts,
  closed loops (enclosures). Layout-engine + UI extensions.
- **8.E — Bake-to-GLB + slope.** `bake_fence.py` (assemble → extension-
  free GLB for model-viewer/Quick Look); stepped vs racked slope in the
  layout engine.

### Decisions taken (defaults — redirectable)

1. Components: generate panel-only + post-only separately.
2. v1 scope: straight runs first (8.A–8.C); corners/enclosures in 8.D.
3. One fence data model (`FenceSpec`); 2D-pole convergence deferred,
   existing 2D code untouched.
4. Flat-yard assumption first; slope deferred to 8.E.

### Risks

- Panel/post component isolation quality (masking posts out of the panel
  crop). Mitigation: the nano-banana isolate already does clean
  extraction; verify per-component as in Phase 7.
- Layout↔render drift if the algorithm is duplicated in Python and JS.
  Mitigation: 8.C fetches layout from the Python `/api/fence/layout`
  endpoint (single source of truth) rather than re-implementing in JS.
- Mobile instancing perf for long runs. Mitigation: measure on device;
  `mergeGeometries` fallback (research notes the trade-off).

## Linked notes

- [POC plan (2D)](./poc-plan.md) — the prior phase this builds on
- [Architecture](./architecture.md) — the adapter pattern this AR work plugs into
- [Stack decision](./stack-decision.md) — vendor rationale
- `research/INDEX.md` — full AR research index
- `research/image-to-3d/synthesis.md` — image→3D recommendation feeding Phase 7
- `research/multi-section-fence/findings.md` — kit-of-parts + runtime-assembly research feeding Phase 8
- `research/ar-survey/06-synthesis/index.md` — comparison matrix + per-use-case stack recs

#task #project #ar
