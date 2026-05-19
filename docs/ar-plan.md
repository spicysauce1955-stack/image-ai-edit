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

## Linked notes

- [POC plan (2D)](./poc-plan.md) — the prior phase this builds on
- [Architecture](./architecture.md) — the adapter pattern this AR work plugs into
- [Stack decision](./stack-decision.md) — vendor rationale
- `research/INDEX.md` — full AR research index
- `research/ar-survey/06-synthesis/index.md` — comparison matrix + per-use-case stack recs

#task #project #ar
