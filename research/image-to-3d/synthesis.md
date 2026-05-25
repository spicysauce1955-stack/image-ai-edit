# Synthesis — recommendation for this project

**Date:** 2026-05-25. Knowledge-only (no implementation yet, per task).

## The ask, restated

Automate creating 3D models from images, ideally **multiple photos of
one object from different angles**, output usable by the AR pipeline.

## What the research settles

1. There are three regimes (`README.md`): generative single-image,
   **generative sparse multi-view**, and metric photogrammetry. Our
   ask + our use case (AR-placed décor, not survey measurement) lands
   squarely in **generative sparse multi-view**.
2. Multiple real photos **do** improve fidelity — big gains 1→4 views,
   diminishing past ~8 (`02-model-landscape.md`). So a 3–4-angle input
   is the practical sweet spot.
3. Four hosted services take multi-image input and return GLB:
   **Meshy, Tripo, Rodin, fal.ai (Hunyuan3D / TRELLIS)**
   (`01-hosted-apis.md`).
4. Metric photogrammetry / scan apps (KIRI, Polycam) exist if we ever
   need faithful real-object capture, but are out of scope for the
   primary flow (`03-photogrammetry-and-neural.md`).

## Recommended path

**Generative sparse multi-view via a fal.ai-hosted endpoint** (Hunyuan3D
3.1 for up to 8 views, or TRELLIS multi), with **Meshy Multi-Image-to-3D
as the cross-check alternative.**

Why fal.ai first:
- **Reuses existing infra.** We already hold `FAL_KEY` and have a
  working queue/subscribe client + download/retry helpers in
  `src/ai_edit/providers/falai.py`. A multi-image-to-3D handler is a new
  class in that file, not a new provider — mirrors how `FalAINanoBanana`,
  `FalAIFluxRefInpaint`, etc. were added.
- **Multi-view native.** Hunyuan3D 3.1 accepts up to 8 angles; TRELLIS
  has a dedicated `/multi` endpoint.
- **GLB + PBR out**, which drops into `ARStore` with no conversion;
  USDZ either comes from the model or via the existing
  `Format3DConverter` ABC (Phase 4.A bundler is GLB-only today, so USDZ
  conversion is its own follow-up).
- **Commercial terms** are workable (verify per-model page).

Why Meshy as the documented alternative: cleanest dedicated
Multi-Image-to-3D endpoint (1–4 `image_urls`), but it's a new provider +
new API key, and free-tier outputs are CC-BY. Good for A/B quality
comparison once the fal path works.

## How it maps onto existing code (no new abstractions needed)

The `Scene3DModel` ABC added in Phase 0 is **already multi-view-ready**:

```python
# src/ai_edit/models/base.py  (existing)
class Scene3DModel(ABC):
    async def generate(
        self,
        prompt: str,
        references: list[tuple[bytes, str]] | None = None,  # ← multiple images already
        *, model=None, target_format="glb", **kwargs,
    ) -> Scene3DResponse: ...
```

`references` is already a *list* of `(bytes, mime)` — i.e. it can carry
the front/back/left/right photos with zero signature change. The
implementation work is just:
1. A `FalAIMultiImageTo3D` handler in `providers/falai.py` implementing
   `Scene3DModel`, uploading the reference images and polling for the GLB.
2. Writing the resulting `Scene3DResponse` GLB into the `ARStore` under a
   `scene_id` — exactly what `catalog_fetch.fetch_entry` already does for
   downloaded catalog assets, so the AR routes serve it unchanged.
3. (Later) `Format3DConverter` for USDZ if the model doesn't return one.

So the architecture laid down in Phases 0/2/4 already accommodates this;
the new work is one provider class + a thin pipeline entrypoint, not a
redesign.

## What to verify before building (open questions)

1. **Exact fal.ai multi-image params** — confirm the field name and max
   view count on the live Hunyuan3D 3.1 / TRELLIS-multi model pages
   (image array vs named slots; how camera/angle hints are passed).
2. **Per-model commercial-license text** on the chosen fal endpoint.
3. **Latency budget** — Hunyuan3D multi-view texturing ~18–30 s+ on some
   hosts; decide sync-wait vs background-job UX for the web flow.
4. **USDZ** — does the chosen model emit USDZ, or do we need a converter
   pass for the iOS Quick Look path?
5. **Cost ceiling** — ~$0.16 (Replicate hunyuan3d-2) to ~$0.375+
   (fal Hunyuan3D 3.1 Pro w/ options) per generation; set a budget guard.
6. **Quality bar** — run the same 3–4 photos through fal-Hunyuan3D vs
   Meshy vs Tripo and eyeball the GLB in `/ar/<id>/live` before committing.

## Explicitly NOT recommended for the primary flow

- Photogrammetry (COLMAP/RealityCapture) — needs dozens of photos +
  desktop processing; metric accuracy we don't need.
- Luma AI — splat-only, no mesh export, officially sunsetting.
- Single-image-only models (SF3D/SPAR3D) — they ignore the multi-angle
  input the task specifically wants (keep as a fast fallback only).

## Suggested next step (when we move from knowledge → build)

A small, well-tested Phase (mirrors the AR phases): add
`FalAIMultiImageTo3D` implementing `Scene3DModel`, a `scripts/poc_3d.py`
that takes N image paths + a prompt and writes a GLB to `out/scenes/<id>/`,
mocked-HTTP unit tests + one `RUN_NETWORK_TESTS=1` integration test, then
wire it behind `/api` so the web UI can request a generation. Verify the
output in the existing `/ar/<id>` and `/ar/<id>/live` viewers.
