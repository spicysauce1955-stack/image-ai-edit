# Hosted image→3D APIs — multi-image support (2025–2026)

**Source:** Tavily `pro` research, 2026-05-25. Project constraint:
hosted APIs only, no self-hosted weights (`docs/stack-decision.md`).
Output target: GLB (+ optionally USDZ) to drop into `ARStore`.

---

## TL;DR — who accepts multiple images

| Service | Multi-image input | Format of input | GLB out? | Commercial license | Notes |
|---|---|---|---|---|---|
| **Meshy** Multi-Image-to-3D | ✅ **1–4 images** | `image_urls` array (>4 → first 4 used) | ✅ + USDZ/FBX/OBJ/STL/BLEND | Paid tiers own assets; **free tier = CC-BY 4.0** | ~30–60 s; credits (5 no-texture / 15 textured) |
| **Tripo** multiview | ✅ **2–4 images** | `images` array; `concat` (multi-view) vs `fuse` modes | ✅ (glTF 2.0 default) + USD/FBX/OBJ/STL/3MF | Free tier **not** commercial; Pro/Max ($19.90/mo) commercial | up to 4K PBR; multiview reportedly <8 s |
| **Hyper3D Rodin** | ✅ **auto when >1 image** (up to ~5) | `concat` / `fuse`; first image drives materials | ✅ + FBX/OBJ/STL/USDZ | Commercial allowed (vendor) | 2K–500K face presets; 4K PBR (HighPack); ~60–120 s |
| **fal.ai Hunyuan3D 3.1** | ✅ **up to 8-angle multi-view** | model-page params | ✅ + OBJ/FBX/USDA/USDZ | per-model page (check) | ~$0.375/gen + $0.15 each for PBR/multi-view/face-count; up to 1.5M poly, 4K PBR |
| **fal.ai TRELLIS (multi)** | ✅ multi-image endpoint | `fal-ai/trellis/multi` | ✅ | TRELLIS = commercial-friendly (MIT-ish) | auto polycount 40K–1.5M; texture 1024–4096 |
| **Replicate** `tencent/hunyuan3d-2` | ✅ (model variant) | per model | ✅ | per model | ~$0.16/run — cheapest explicit price found; ~3 min |
| **Stability SF3D / SPAR3D** | ❌ single-image only | one image | ✅ (UV-unwrapped) | SPAR3D Community License (commercial; >$1M rev → contact) | sub-second to ~1 s; SPAR3D adds point-cloud stage for backside |
| **Luma AI** | video / zip of images (multi-frame) | video or image zip | GLTF/USDZ/OBJ + NeRF/splat | Pro = commercial | scene/NeRF-oriented, not per-object LOD; **officially no longer actively updated** |
| **CSM Cube** | image→3D (single documented) | — | — (not stated) | plan-gated | ~30 s; sparse public docs |
| **Sloyd / Kaedim / Alpha3D / Masterpiece X** | mostly single-image; multi-image **unconfirmed** | — | varies | varies | thin public API docs; verify directly |

**Bottom line:** four hosted services explicitly take multiple angled
photos of one object and return GLB — **Meshy, Tripo, Rodin, and
fal.ai's Hunyuan3D/TRELLIS**. Three of those (Tripo, Rodin, Hunyuan3D
via fal) are reachable through fal.ai, which we already authenticate
against (`FAL_KEY`).

---

## Detail per service

### Meshy — Multi-Image-to-3D
- Endpoint: `POST /openapi/v1/multi-image-to-3d`, body has `image_urls`
  (array) or `input_task_id`. Single-image variant: `image-to-3d`.
- **1–4 images**; more than 4 → only first 4 used.
- Returns task `id`; poll for `model_urls`.
- Formats: GLB, FBX, OBJ, USDZ, STL, BLEND. PBR via AI Texturing.
- Pricing: credits (e.g. 5 untextured / 15 textured on Meshy-6). Free
  monthly credits; Pro/Studio raise limits.
- **License gotcha:** free-plan outputs are CC-BY 4.0 (attribution,
  limited commercial). Paid subscribers own outputs.
- Docs: `https://docs.meshy.ai/en/api/multi-image-to-3d`

### Tripo — multiview-to-3D
- Endpoint: `POST /v1/3d-models/tripo/multiview-to-3d/`, `images` array.
- **2–4 images.** `concat` = treat as multi-view of one object; `fuse`
  = combine multiple objects.
- Default GLB (glTF 2.0); also USD/FBX/OBJ/STL/3MF. PBR maps (base
  color, roughness, metallic, normal) up to 4K.
- Fast (tutorials claim multiview <8 s).
- **License gotcha:** free account models not for commercial use;
  Pro/Max tiers grant commercial rights.
- Docs: `https://tripo3d.ai/api`

### Hyper3D Rodin
- Auto-switches to multi-image when >1 image uploaded; `condition_mode`
  = `concat` (multi-view of one object) or `fuse`. Up to ~5 images;
  first image drives materials.
- Formats: GLB, FBX, OBJ, STL, USDZ; PBR (albedo/normal/roughness/
  metallic) up to 4K. Quad/tri presets ~2K–500K faces.
- Reachable via `fal-ai/hyper3d/rodin` and Replicate (`hyper3d/rodin`,
  ~$0.40/output). ~60–120 s.
- Commercial use allowed per vendor.

### fal.ai-hosted (the path that reuses our infra)
- We already have `FAL_KEY` and a queue/subscribe client in
  `src/ai_edit/providers/falai.py`.
- **Hunyuan3D 3.1**: up to **8-angle multi-view**, PBR up to 4K, up to
  1.5M polys. ~$0.375/gen (+$0.15 each for PBR / multi-view / face
  count). `https://fal.ai/hunyuan-3d`
- **TRELLIS multi**: `fal-ai/trellis/multi` multi-image endpoint; GLB;
  auto polycount. `https://fal.ai/models/fal-ai/trellis/multi/api`
- **Tripo & Rodin** also wrapped as fal.ai models.
- fal default concurrency 2 (429 on exceed); standard submit/status/
  result + `@fal-ai/client` SDK pattern — same shape `falai.py` already
  uses via `fal_client.subscribe`.

### Stability — SF3D / SPAR3D (single-image only)
- Both **single-image**, very fast (SF3D ~0.5 s; SPAR3D ~0.7 s). SPAR3D
  conditions on a generated point cloud to improve the unseen back.
- GLB, UV-unwrapped. Platform credits: SF3D 10 / SPAR3D 4 (1 credit =
  $0.01). SPAR3D Community License = commercial OK below $1M revenue.
- Not multi-view — listed for completeness / fallback.

### Luma AI (video/multi-frame → NeRF/splat)
- Ingests video or a zip of images → NeRF / Gaussian splat scene.
  Exports GLTF/USDZ/OBJ/PLY. Enterprise API for programmatic use.
- Scene-oriented, not per-object LOD GLB. **Officially no longer
  actively updated** as of 2026 (still usable). Treat as legacy.

### Thin / unverified (need direct confirmation before use)
- **CSM Cube** (`docs.csm.ai`) — image→3D, ~30 s, formats/pricing not
  public in our sources.
- **Sloyd** — single-image, API needs X-API-Key + JWT; multi-image
  unconfirmed.
- **Kaedim** — 2D→3D via API (key + JWT); multi-image params, formats,
  per-run pricing not public.
- **Alpha3D**, **Masterpiece X** — image/text→3D; no hosted multi-image
  API details surfaced.

---

## Decision-relevant facts

- **Cheapest explicit price:** Replicate `tencent/hunyuan3d-2` ~$0.16/run.
- **Best multi-view angle count:** Hunyuan3D 3.1 (up to 8) > Rodin (~5)
  ≈ Meshy (4) ≈ Tripo (4, min 2).
- **Cleanest commercial terms out of the box:** Rodin and the fal.ai
  TRELLIS path; Meshy/Tripo gate commercial use behind paid tiers; watch
  Stability's $1M revenue clause.
- **Reuses existing project infra:** anything via **fal.ai** (`FAL_KEY`
  + `falai.py` queue/subscribe). This is the lowest-friction integration
  and matches the AR plan's earlier "fal.ai-hosted" lean.

---

## References

1. Meshy Multi-Image-to-3D — https://docs.meshy.ai/en/api/multi-image-to-3d
2. Meshy Image-to-3D — https://docs.meshy.ai/en/api/image-to-3d
3. Meshy formats — https://help.meshy.ai/en/articles/9991884-what-3d-file-formats-do-you-support
4. Meshy pricing — https://meshy.ai/pricing
5. Tripo API — https://tripo3d.ai/api
6. Tripo export formats — https://tripo3d.ai/tutorials/tripo-ai-export-formats
7. Hyper3D Rodin (fal) — https://fal.ai/models/fal-ai/hyper3d/rodin
8. Rodin API spec — https://developer.hyper3d.ai/api-specification/rodin-generation_reset_v
9. fal.ai Hunyuan3D — https://fal.ai/hunyuan-3d
10. fal.ai TRELLIS multi — https://fal.ai/models/fal-ai/trellis/multi/api
11. fal.ai TRELLIS-2 API ref — https://fal.ai/docs/model-api-reference/3d-api/trellis-2
12. Replicate hunyuan3d-2 — https://replicate.com/tencent/hunyuan3d-2
13. Stability SPAR3D — https://stability.ai/news-updates/stable-point-aware-3d
14. Stable Fast 3D — https://stablefast3d.com
15. Stability pricing — https://platform.stability.ai/pricing
16. Luma API — https://docs.lumalabs.ai/docs/api
17. fal.ai pricing — https://fal.ai/pricing
