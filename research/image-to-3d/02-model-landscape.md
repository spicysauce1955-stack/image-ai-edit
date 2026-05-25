# Image→3D model landscape + the multi-view science (2025–2026)

**Source:** Tavily `pro` research, 2026-05-25. This is the "what's under
the hood" companion to `01-hosted-apis.md`. Read it to understand *why*
multi-view helps and which model families the hosted APIs wrap.

---

## The key distinction (this is the whole point)

"Multi-view" means two very different things:

- **Generative multi-view** — the model is *given* (or *synthesizes*) a
  handful of views and produces a plausible full 3D object, hallucinating
  whatever it can't see. Tolerant of sparse input. This is what Meshy /
  Tripo / Rodin / Hunyuan3D do.
- **Photogrammetric multi-view** — many real, overlapping photos with
  recoverable camera poses produce a *metric* reconstruction (real
  measurements, no hallucination). Covered in `03-photogrammetry-and-neural.md`.

A pattern that dominates the generative side: **"generate novel views
first, then reconstruct."** A 2D diffusion model (Zero123 / MVDream /
SV3D family) invents consistent extra views from your input, then a
reconstruction backend (LRM / triplane / Gaussian predictor) fuses them
into a mesh. InstantMesh, CRM, and Unique3D all work this way.

---

## Does giving it multiple real photos actually help?

**Yes, materially — up to a point.** Across the surveyed papers:

- Going from **1 → ~4 views** yields large geometric gains (Chamfer
  distance, F-score). InstantMesh and CRM both reconstruct from 6
  views; LGM trains on 4–8.
- Gains continue to **~6–8 views**, then diminish for these sparse
  pipelines.
- SPAR3D's ablation: removing its point-cloud stage degrades geometry —
  evidence that extra geometric priors (whether real views or generated
  point clouds) materially improve the unseen back of the object.

**Practical rule of thumb:** feed the multi-image APIs **3–4 clean
angles** (e.g. front, back, two sides). That captures most of the
benefit. More than ~8 buys little on these generative models — and only
photogrammetry truly scales with photo count.

**Caveat:** "multi-view" on a generative API still hallucinates surfaces
not covered by your photos and is **not metric-accurate**. Fine for AR
décor; wrong for "how wide is this fence, exactly."

---

## Model families (what the APIs wrap)

| Model | Input | Output | Multi-view role | Hosted? |
|---|---|---|---|---|
| **TRELLIS** (Microsoft) | single image / text | mesh, Gaussian, NeRF (O-Voxel latent) | primarily single-image; fal exposes a multi endpoint | fal.ai, NVIDIA NIM; MIT-ish |
| **Hunyuan3D 2.0/2.1/3.1** (Tencent) | image/text/sketch; up to 8-view (3.1) | mesh + PBR (albedo/metallic/roughness) | dense multi-view supervision in training; 3.1 takes multi-view input | fal.ai, Replicate; weights open (2.1) |
| **InstantMesh** | single image → 6 generated views | textured mesh | Zero123++ frontend → LRM fusion | GitHub (open) |
| **CRM** | single image → 6 orthographic views | textured mesh | multi-view diffusion → conv reconstruction | open |
| **LGM** | image/text, 1–4 views | 3D Gaussian splats | cross-view attention U-Net | HF (open) |
| **Zero123 / Zero123++ / Stable Zero123** | single image | novel views / orbital video | *frontend* — generates the views others reconstruct | HF |
| **SV3D** (Stability) | single image (+ optional camera path) | 21-frame orbital video / multi-view | latent video diffusion frontend | Stability |
| **MVDream / Wonder3D / Unique3D / Era3D** | single image | multi-view images → mesh | various multi-view-diffusion → mesh pipelines | open (papers/repos) |
| **SF3D / SPAR3D** (Stability) | single image | UV-unwrapped textured mesh | single-image feed-forward (SPAR3D adds point stage) | Stability API |
| **CLAY / Rodin** | multi-modal incl. multi-view | PBR assets / sculpts | controllable generative; multi-view conditioning | Rodin hosted |
| **MV-Adapter** | image/text | multi-view images | adapter that adds multi-view to SD/SDXL | open |
| **Real3D** | posed multi-view real images | triplane/implicit | scales reconstruction on *real* images; needs canonical poses | ICCV'25 paper |

## Architectural taxonomy (four patterns)

1. **Multi-view diffusion frontend → reconstruction backend** — strongest
   2D priors, best texture realism; quality bounded by the view
   generator (InstantMesh, CRM, Unique3D).
2. **Direct feed-forward reconstruction** (triplane/transformer/conv) —
   fastest, sub-second possible (SF3D), but hallucinates unseen faces.
3. **Gaussian-splat predictors** (LGM, TRELLIS GS output) — photorealistic
   render, weaker explicit metric geometry; needs a splat→mesh step for
   traditional pipelines (see `03-...md`).
4. **Latent video / adapter multi-view generators** (SV3D, MV-Adapter,
   Zero123, MVDream) — modular frontends, not standalone 3D.

## Output representations & what we want

Our AR pipeline wants **explicit textured mesh → GLB with PBR**. That
points at the mesh-output families (Hunyuan3D, TRELLIS mesh mode, Tripo,
Rodin, InstantMesh-class). Gaussian-splat outputs (LGM, raw TRELLIS GS,
Luma) need a splat→mesh conversion before they fit `<model-viewer>` /
Scene Viewer / Quick Look.

---

## References

1. TRELLIS — https://github.com/microsoft/TRELLIS
2. Hunyuan3D 2.1 — https://huggingface.co/tencent/Hunyuan3D-2.1
3. Hunyuan3D paper — https://arxiv.org/html/2506.15442v1
4. InstantMesh — https://github.com/tencentarc/instantmesh ; paper https://arxiv.org/html/2404.07191v1
5. CRM — https://ml.cs.tsinghua.edu.cn/~zhengyi/CRM ; paper https://arxiv.org/html/2403.05034v1
6. LGM — https://arxiv.org/abs/2402.05054
7. Zero123++ — https://ar5iv.labs.arxiv.org/html/2310.15110
8. Stable Zero123 — https://huggingface.co/stabilityai/stable-zero123
9. SV3D — https://sv3d.github.io
10. MVDream — https://arxiv.org/html/2308.16512v3
11. Wonder3D — https://cg.cs.tsinghua.edu.cn/papers/CVPR-2024-Wonder3D.pdf
12. Unique3D — https://arxiv.org/html/2405.20343v1
13. SPAR3D — https://huggingface.co/papers/2501.04689
14. SF3D — https://stability.ai/news-updates/introducing-stable-fast-3d
15. MV-Adapter — https://github.com/huanngzh/MV-Adapter
16. Real3D — https://openaccess.thecvf.com/content/ICCV2025/papers/Jiang_Real3D_Towards_Scaling_Large_Reconstruction_Models_with_Real_Images_ICCV_2025_paper.pdf
