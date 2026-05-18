---
created: 2026-05-18
tags: [project, task, ar]
---

# AR plan — WebAR-first, modular, extendable

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

### Phase 2 — Image→3D provider
- [ ] Pick generator (default: Meshy AI). Document the choice in `docs/stack-decision.md`
- [ ] `providers/meshy.py` implements `Scene3DModel.generate(prompt, references)` → returns a `Scene3DResponse` carrying GLB
- [ ] GLB→USDZ conversion behind `Format3DConverter`. First impl: Apple's `usdzconvert` if on macOS; portable fallback via fal.ai or Replicate conversion endpoint
- [ ] Tests: mocked HTTP for unit; one slow integration test gated by `RUN_NETWORK_TESTS=1`
- [ ] `scripts/poc_3d.py REFERENCE.jpg "a wooden fence panel"` writes both `.glb` and `.usdz` into `out/scenes/<id>/`

### Phase 3 — Wire AR into the existing pipeline + web UI
- [ ] `pipeline/ar_preview.py`: runs the existing 2D `insert_object` AND `Scene3DModel.generate` in parallel
- [ ] Web UI: after the 2D composite renders, "View in AR" button → `/ar/{scene_id}`
- [ ] Integration test: end-to-end against a real reference image, gated by `RUN_NETWORK_TESTS=1`

### Phase 4 — Quality + observability
- [ ] Post-process every generated GLB through `gltfpack` (meshopt) + KTX2 textures via Khronos `glTF-Compressor`
- [ ] glTF validator on every output (fail-closed)
- [ ] Structured logs around AR generation: asset bytes, gen latency, conversion success
- [ ] CI smoke: known reference image → asset under target size, validator passes, AR route returns expected MIMEs

### Phase 5 — Hooks (interfaces only, do not implement)
- [ ] `MeshFromSegmentation` capability stub — future SAM + monocular depth → mesh path
- [ ] `GaussianSplatModel` capability stub — future Luma/Polycam-style input
- [ ] Migration note added to `docs/architecture.md` documenting how a WebXR-SLAM / AR Foundation native track would plug into the same `Scene3DResponse` plumbing

## Repo layout (target after Phase 3)

```
image-ai-edit/
├── docs/
│   └── ar-plan.md                            # this file
├── src/ai_edit/
│   ├── models/base.py                        # +Scene3DAsset, Scene3DResponse, Scene3DModel, Format3DConverter
│   ├── providers/
│   │   └── meshy.py                          # NEW (Phase 2)
│   ├── pipeline/
│   │   ├── ar_preview.py                     # NEW (Phase 3)
│   │   └── ar_store.py                       # NEW (Phase 1)
│   └── server/app.py                         # +AR routes (Phase 1)
├── scripts/
│   └── poc_3d.py                             # NEW (Phase 2)
├── tests/
│   ├── conftest.py                           # NEW (Phase 0)
│   ├── models/test_scene3d_dataclasses.py    # NEW (Phase 0)
│   ├── server/test_ar_routes.py              # NEW (Phase 1)
│   └── providers/test_meshy.py               # NEW (Phase 2)
└── out/
    └── scenes/<scene_id>/{model.glb,model.usdz}  # NEW (Phase 1+)
```

## Open decisions before Phase 2

- **Generator vendor**: default Meshy AI. Re-evaluate after first integration: Tripo (cheaper), Stable Point Aware 3D via Replicate (more permissive license), Rodin (newer, possibly higher quality). See `research/ar-survey/05-tech-stack/findings.md` for context.
- **GLB→USDZ conversion**: on dev machines `usdzconvert` is fine; on a server we need a hosted endpoint. fal.ai has a USD conversion endpoint — confirm before committing.
- **Asset persistence**: filesystem (`out/scenes/`) is fine until multi-tenant. Object storage (Cloudflare R2) is the natural Phase 4+ upgrade per the synthesis doc.

## Risks

- Meshy / image-to-3D quality may not match the 2D composite — the AR fence may look "AI-generated" while the 2D fence looks photoreal. Mitigations: try Tripo / SPAR3D / Rodin; consider hybrid pipelines (e.g. image→sparse 3D point cloud → manual mesh template fill).
- USDZ conversion edge cases (PBR material loss, texture compression incompatibilities). Mitigation: validate with Apple's USDZ tools in Phase 4 CI.
- `<model-viewer>` AR button does not appear if device fails capability detection — common cause is wrong MIME or missing `ios-src`. Mitigation: explicit MIME tests in Phase 1; manual phone smoke in runbook.
- Hosting raw GLBs is fine; hosting auto-generated USDZs that violate Apple's spec breaks Quick Look. Mitigation: Phase 4 validator.

## Linked notes

- [POC plan (2D)](./poc-plan.md) — the prior phase this builds on
- [Architecture](./architecture.md) — the adapter pattern this AR work plugs into
- [Stack decision](./stack-decision.md) — vendor rationale
- `research/INDEX.md` — full AR research index
- `research/ar-survey/06-synthesis/index.md` — comparison matrix + per-use-case stack recs

#task #project #ar
