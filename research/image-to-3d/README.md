# Image → 3D research (multi-view focus)

**Date:** 2026-05-25
**Why this exists:** the deferred Phase 2 of the AR plan was "AI image→3D".
We're now revisiting it with a specific requirement: **automate creating
3D models from images, ideally from multiple photos of the same object
from different angles** (front/back/left/right or orbital). Output must
fit the existing AR pipeline (a GLB landing in the `ARStore`, served at
`/ar/<id>/model.glb`).

This folder is **knowledge only** — no implementation yet (per the
task). It feeds the `Scene3DModel` capability ABC that already exists in
`src/ai_edit/models/base.py` (Phase 0) and is reserved as the AI-gen
hook in `docs/ar-plan.md` Phase 5.

## Layout

| File | What |
|---|---|
| [`01-hosted-apis.md`](./01-hosted-apis.md) | **The decision-relevant one.** Hosted image→3D APIs that accept multiple images — Meshy, Tripo, Rodin, fal.ai (TRELLIS / Hunyuan3D), Replicate, Stability, Luma, etc. Multi-image support, formats, pricing, licensing |
| [`02-model-landscape.md`](./02-model-landscape.md) | The underlying models (TRELLIS, Hunyuan3D, InstantMesh, LGM, Zero123, SV3D…) + the science of *when multiple real photos actually improve fidelity* |
| [`03-photogrammetry-and-neural.md`](./03-photogrammetry-and-neural.md) | The metric-accurate path: classical photogrammetry (COLMAP, RealityCapture, Metashape, Meshroom) + neural (NeRF, 3D Gaussian Splatting, 3DGS→mesh) + hosted scan apps (KIRI, Polycam, Luma). Capture best practices |
| [`synthesis.md`](./synthesis.md) | **Recommendation for THIS project.** Which path, which provider, how it maps onto `Scene3DModel`, and what to verify before building |

## The one-paragraph answer

There are three different things people mean by "images → 3D", and the
right tool depends on which one we want:

1. **Generative single-image → 3D** — one photo, the model *hallucinates*
   the unseen sides. Fast, cheap, tolerant. (SF3D, SPAR3D, TRELLIS.)
2. **Generative sparse multi-view → 3D** — 1–4 (sometimes up to 8) real
   photos from different angles; the model uses them to constrain
   geometry and texture, filling whatever gaps remain. **This is the
   sweet spot for our ask** and is offered as a hosted API by Meshy
   (Multi-Image-to-3D), Tripo (multiview), Rodin (concat mode), and
   fal.ai's Hunyuan3D / TRELLIS. Output: GLB with PBR.
3. **Metric photogrammetry / neural reconstruction** — many photos
   (dozens to hundreds, ≥60% overlap) for a survey-accurate scan. Needs
   COLMAP / RealityCapture / a scan app, not a single API call. Overkill
   for AR-placed yard décor; necessary only if real-world measurement
   matters.

For our AR use case the recommendation (see `synthesis.md`) is **option
2 via a fal.ai-hosted multi-image endpoint**, because it accepts the
multiple-angle input the task asks for, returns GLB, has commercial-use
terms, and reuses the `FAL_KEY` + queue infra already in
`src/ai_edit/providers/falai.py`.
