# AR pipeline

Image-to-3D + cross-platform WebAR delivery. Phase 2 of the project.

## End-to-end flow

```
[ref1.jpg, ref2.jpg, ref3.jpg, ...]
    │
    ▼  Meshy · Multi-Image-to-3D       (typ. 5–10 min)
    │       returns GLB + USDZ
    ▼
in-memory store keyed by AR id
    │
    ▼
GET /ar/{id}                            (browser)
    │
    ▼  <model-viewer ar src=GLB ios-src=USDZ>
        iOS  → AR Quick Look (LiDAR occlusion on supported devices)
        Android → Scene Viewer (ARCore depth)
```

## Setup

```bash
uv pip install -p .venv/bin/python -e ".[server]"
echo "MESHY_API_KEY=msy_..." >> .env
.venv/bin/python scripts/serve.py
```

Get a Meshy API key from https://meshy.ai (paid tier required for commercial asset ownership — see `docs/stack-decision.md`).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/build-ar` | Multipart with one or more `references` files. Returns `{id, viewer_url, glb_url, usdz_url}`. **Holds the connection open for the entire Meshy job (minutes).** |
| `GET` | `/ar/{id}` | `<model-viewer>` page that loads the asset and exposes "View in your space". |
| `GET` | `/ar/{id}/model.glb` | Raw GLB bytes (Android Scene Viewer / WebGL). |
| `GET` | `/ar/{id}/model.usdz` | Raw USDZ bytes (iOS AR Quick Look). |

## Example: curl

```bash
curl -sS -X POST http://127.0.0.1:8000/api/build-ar \
  -F "references=@fence-front.jpg" \
  -F "references=@fence-side.jpg" \
  -F "references=@fence-back.jpg"
# → {"id":"e8f2…", "viewer_url":"http://127.0.0.1:8000/ar/e8f2…", ...}
```

Then open the viewer URL on a phone.

## How `<model-viewer>` picks an AR mode

The viewer page sets `ar-modes="webxr scene-viewer quick-look"`. The browser walks that list:

- **iOS Safari/Chrome** → `quick-look` → loads the USDZ via AR Quick Look.
- **Android Chrome** → `scene-viewer` → loads the GLB via Scene Viewer.
- **Browsers with WebXR support** (rare on mobile, common on AR headsets) → `webxr` → loads the GLB inline.
- **Anything else** → falls back to plain WebGL inside the viewer.

This is why we always generate **both** GLB and USDZ — without USDZ there is no no-install AR path on iOS.

## State and persistence

The in-memory `_AR_STORE` in `server/app.py` is the simplest thing that works for a POC:

- Generated assets evict on process restart.
- Multiple uvicorn workers won't share the store — run a single worker for the POC.
- File size is bounded by RAM; a 30k-poly textured GLB is ~2–8 MB.

For production swap the dict for object storage (S3, R2) and serve `/ar/{id}/model.glb` as a redirect to a presigned URL. The interface stays the same.

## Why Meshy

See `docs/stack-decision.md` for the full vendor matrix. Short version: Meshy is the only hosted image-to-3D service that returns **GLB + USDZ in one call** with **commercial asset ownership for paid users** — exactly what the no-install WebAR path needs.

Alternates if you outgrow Meshy:

- **fal.ai · Hunyuan3D v2** — cheaper per gen, GLB only (no USDZ). Use for Android-only flows.
- **Tripo 3D** — multiview support, similar quality. Worth A/B testing per object class.
- **Stability Stable Fast 3D** — sub-second generation, but Community License caps commercial use at $1M revenue.

## Caveats and known limits

- **Latency.** `/api/build-ar` blocks for the whole Meshy job. For interactive UX, refactor to a job queue + status endpoint pattern (mirrors fal.ai's queue API).
- **Cost.** Multi-Image-to-3D is ~$0.30–0.50 per generation. Cache aggressively per product.
- **Number of views.** 1 photo "works" but quality jumps with 3–8 well-lit angles.
- **Repeating-pattern objects** (fences, fabric, foliage) historically confuse photogrammetry-style models. Test before committing.
- **Asset placement is single-session.** We don't anchor with VPS. If you need persistent AR placement across sessions, integrate ARCore Geospatial or Niantic Lightship VPS — beyond the POC.
