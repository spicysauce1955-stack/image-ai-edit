---
created: 2026-05-03
tags: [reference, project]
---

# API catalog (2025–2026)

Full vendor matrix from the research pass. Use this when picking fallbacks or swapping a layer.

## A · Hosted segmentation / scene understanding

| Service | Output | Pricing | Notes |
|---|---|---|---|
| **Replicate · Grounded-SAM** | Text → pixel mask | ~$0.0014/run, ~2s | Picked. Open-vocab. |
| **Replicate · SAM 2** | Promptable masks (pt/box) | ~$0.0097/run, ~10s | Picked for click-refine. |
| **Replicate · Florence-2 large** | Multi-class masks, OCR, region | ~$0.0019/run, ~2s | Solid alternative. |
| **fal.ai · SAM 2 Auto-Segment** | Masks | Per-call | Lower latency in some regions. |
| **fal.ai · Florence-2 large** | Masks + region desc | Per-call | — |
| **Roboflow · Florence-2 serverless** | Multi-class masks | Plan-based | Good if already using Roboflow pipelines. |
| Google Gemini 2.5/3 vision | Boxes + spatial reasoning | Generous free tier | Use for "what's in this scene", not pixel masks. |
| Google Cloud Vision / AWS Rekognition / Azure Vision / Clarifai | Labels + boxes | Per 1k | Skip — not mask-grade. |

Docs:
- https://replicate.com/schananas/grounded_sam/api
- https://replicate.com/meta/sam-2/api
- https://replicate.com/lucataco/florence-2-large
- https://fal.ai/models/fal-ai/sam2/auto-segment/api
- https://docs.roboflow.com/deploy/supported-models/florence-2

## B · Hosted generative editing / object insertion

| Service | Reference image? | Mask? | License | Notes |
|---|---|---|---|---|
| **Google Gemini 2.5 Flash Image** ("Nano Banana") | ✅ multi-image | ✅ via prompt | Commercial OK | **Picked.** |
| OpenAI gpt-image-1 | ✅ multi-image | ✅ explicit `mask` | Commercial OK | Higher consistency, slower, pricier. |
| **BFL FLUX.1 Kontext Pro/Max** | ✅ in-context | ✅ | Pro = commercial; Dev = NC | Best edge fidelity. Quality fallback. |
| BFL FLUX.1 Fill | ❌ text only | ✅ | Pro = commercial | Pure inpainting/outpainting. |
| Runway Gen-4 Image (`referenceImages`) | ✅ up to 3 refs | partial | Commercial OK | Stylish refs, weaker geometry. |
| Stability Stable Image Edit (Inpaint, Search-and-Replace, Outpaint) | partial | ✅ | Community license, $1M cap | Cheap fill. |
| **Adobe Firefly Services** (Generative Fill, Object Composite) | ✅ | ✅ | **Indemnified, licensed data** | Legal fallback. |
| **Bria AI** (Eraser, Gen-Fill, Product Placement) | ✅ | ✅ | **Indemnified, licensed data** | Legal fallback. |
| Photoroom API | ✅ | partial | Commercial OK | AI shadows, product staging. |
| Picsart Programmable Image API · Inpaint | ✅ | ✅ | Commercial | — |
| ClipDrop API · Replace Background | ✅ | partial | Commercial | — |
| Cloudinary AI (generative_replace, generative_background) | partial | partial | Per asset | Useful if already on Cloudinary. |
| Recraft, Ideogram Edit | partial | ✅ | Commercial | Less mature for product insertion. |

Docs:
- https://ai.google.dev/gemini-api/docs/image-generation
- https://docs.bfl.ai/kontext/kontext_text_to_image
- https://developer.adobe.com/firefly-services/docs/firefly-api/
- https://docs.bria.ai/image-editing/v2-endpoints/gen-fill
- https://docs.photoroom.com/

## C · Lighting / harmonization

- **fal.ai · IC-Light** — hosted relighting. https://fal.ai/models
- **Magnific Relight** — paid relighting service.
- Photoroom AI Shadows — built into Photoroom edits.

## D · Image-to-3D APIs

| Service | Output | Price | License |
|---|---|---|---|
| **Meshy · Multi-Image-to-3D** | GLB + USDZ + FBX, polycount control | ~20–30 credits/gen | **Paid users own assets.** Picked. |
| Tripo 3D | GLB/GLTF/FBX, multiview | ~40 credits/gen | Tier-based |
| fal.ai · Hunyuan3D v2 | GLB, optional PBR | $0.05–$0.375/gen | Commercial OK |
| Stability Stable Fast 3D / SPAR3D | GLB, ~0.5s | 2 credits/gen | Community, ≤$1M rev |
| Hyper3D Rodin | Multipart upload | ~$0.40/gen | — |
| CSM.ai | OBJ/GLB/FBX/USDZ via Python client | — | — |
| KIRI Engine API | Photogrammetry scans | $1/scan | — |
| Luma / Polycam / RealityScan | App-first, weak API | — | — |

Docs:
- https://docs.meshy.ai/en/api/multi-image-to-3d
- https://fal.ai/models/fal-ai/hunyuan3d/v2

## E · AR / WebAR delivery

| Platform | iOS | Android | Web no-install | Occlusion |
|---|---|---|---|---|
| **`<model-viewer>` + Quick Look + Scene Viewer** | ✅ | ✅ | ✅ | ARKit LiDAR on iOS; depth varies on Android. **Picked.** |
| Plattar WebAR | ✅ | ✅ | ✅ | Hosted wrapper around the same primitives. |
| Zappar / ZapWorks Universal AR | ✅ | ✅ | ✅ | Image/world tracking, JS SDK. |
| Niantic Lightship ARDK / VPS | ✅ | ✅ | Unity-only | Strong meshing + VPS. |
| Snap Camera Kit + World Mesh | ✅ | ✅ | partial | Best occlusion via World Mesh. |
| Apple ARKit / RoomPlan / Object Capture | ✅ | ❌ | ❌ | Best-in-class (LiDAR). |
| Google ARCore + Depth + Scene Semantics + Geospatial | ❌ | ✅ | partial | Per-pixel depth, outdoor classes. |
| ~~8th Wall~~ | — | — | — | **Retired Feb 2026 — do not adopt.** |

Docs:
- https://modelviewer.dev/
- https://developer.apple.com/augmented-reality/quick-look/
- https://developers.google.com/ar/develop/scene-semantics
- https://developers.google.com/ar/develop/depth

#reference #project