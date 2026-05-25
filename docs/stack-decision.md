---
created: 2026-05-03
tags: [decision, project]
---

# Stack decision — 2026

## Use case

> User uploads a photo of their backyard + a photo of a specific fence product → output a photorealistic image of that exact fence placed in the yard, with correct perspective, occlusion behind trees, and matching lighting/shadows.

Later: same fence shown live in AR.

## Constraints

- **No local model hosting.** API keys only.
- Modern, professional 2026 stack.
- Reference-image conditioning is mandatory — must place *that specific fence*, not a generic AI fence.
- Commercial license on outputs preferred; indemnified is a plus.

## Chosen 2D pipeline

```
backyard.jpg + fence_reference.jpg
    │
    ▼
[1] Replicate · Grounded-SAM        # text prompts: "ground, grass, trees, sky, existing fence"
    → multi-class masks (~2s, ~$0.0014/run)
    │
    ▼
[2] (optional UI) Replicate · SAM 2 # user click → refined insertion mask
    │
    ▼
[3] Google Gemini 2.5 Flash Image   # "Nano Banana"
    inputs: [backyard, fence_reference, mask]
    prompt: place fence in masked region, preserve perspective,
            keep trees in front, match lighting
    │
    ▼
[4] (optional) fal.ai · IC-Light    # relight composite to match scene sun
    │
    ▼
final.png
```

## Chosen AR pipeline (later phase)

```
8–20 photos of fence
    │
    ▼
[1] Meshy · Multi-Image-to-3D       # target_formats: ["glb","usdz"]
    │
    ▼
[2] CDN (Cloudflare R2 / S3)
    │
    ▼
[3] <model-viewer ar src="fence.glb" ios-src="fence.usdz">
        iOS  → Quick Look (ARKit, LiDAR occlusion)
        Android → Scene Viewer (ARCore depth/plane)
```

## Why these picks

| Layer | Pick | Why over alternatives |
|---|---|---|
| Segmentation | Grounded-SAM on Replicate | Cheapest + fastest open-vocab text→mask. Florence-2 (Roboflow/fal) is the runner-up if we need Roboflow's pipeline tooling. |
| Mask refine | SAM 2 on Replicate | Click-prompt UX is critical when the auto mask is wrong. |
| Insertion | Gemini 2.5 Flash Image | Best 2026 quality/$ for multi-image conditioned edits. Multi-image inputs + commercial license. Latency ~3–4s. |
| Insertion fallback (quality) | FLUX.1 Kontext Pro (BFL) | Best edge fidelity for product edits. Use when Gemini blurs the fence texture. |
| Insertion fallback (legal) | Adobe Firefly Services / Bria | Indemnified, licensed training data — required if we ship to enterprise. |
| Relight | fal.ai IC-Light | Hosted relighting; cheap polish pass. |
| Image-to-3D | Meshy | Only vendor in survey with **GLB + USDZ + commercial ownership for paid tier** in one call. |
| AR delivery | `<model-viewer>` | Web-standard, zero install, hands off to Quick Look on iOS and Scene Viewer on Android. |

## Explicitly rejected (for now)

- **Google Cloud Vision / AWS Rekognition / Azure AI Vision** — labels and boxes, not pixel-grade masks.
- **8th Wall** — retired Feb 2026; no new projects.
- **Stability Stable Fast 3D** — Community License caps commercial use at $1M revenue → headache later.
- **Self-hosted Mask2Former / SAM 2 / SDXL** — explicitly out of scope.
- **Luma / Polycam / RealityScan** for image-to-3D — mostly app-first; weak hosted API surface for our flow.

## Pricing sketch (per generated composite)

| Step | Cost |
|---|---|
| Grounded-SAM mask | ~$0.0014 |
| SAM 2 refine (when used) | ~$0.0097 |
| Gemini 2.5 Flash Image edit | ~$0.03–0.04 |
| IC-Light relight (optional) | ~$0.01 |
| **Total per image** | **~$0.05–0.07** |
| Meshy image-to-3D (one-off per product) | ~$0.30–0.50 |

## Image→3D provider (Phase 7 · revised 2026-05-25)

**Supersedes the "Meshy" pick in the AR-pipeline table above** for the
generation step. After the deeper multi-view survey
(`research/image-to-3d/`) and the requirement to support multiple
angled photos, the chosen provider is **fal.ai Hunyuan3D 3.1 Pro
(image-to-3D)**.

- **Endpoint:** `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d` (via the
  existing `fal_client.subscribe` path in `providers/falai.py`).
- **Why over Meshy** (the 2026-05-03 pick): reuses `FAL_KEY` + the
  queue/subscribe + download infra already in `falai.py` (no new
  provider account/key); native multi-view; commercial use permitted
  per fal ToS.
- **Multi-view shape — NAMED SLOTS, not an array.** Inputs:
  `front_image_url` (required) + optional `back_image_url`,
  `left_image_url`, `right_image_url`, plus v3.1 diagonals/top/bottom
  (up to 8 angles). Our `Scene3DModel.generate(references=[...])` list
  maps **positionally**: `references[0]`→front, `[1]`→back, `[2]`→left,
  `[3]`→right (then diagonals).
- **Output:** `model_glb` (GLB, `model/gltf-binary`) + OBJ; optional
  PBR maps. First cut serves **GLB only** (USDZ + color fidelity
  deferred to `Format3DConverter` — see `research/image-to-3d/synthesis.md`).
- **Params:** `generate_type` Normal($0.375)/Geometry($0.225);
  `enable_pbr` (+$0.15); `face_count` 40K–1.5M (custom +$0.15);
  multi-view (+$0.15). Fully-loaded multi-view + PBR ≈ **$0.68/gen**.
- **Meshy** remains the documented A/B-quality alternative
  (dedicated 1–4-image `image_urls` endpoint) if fal output disappoints.

#decision #project