# Metric multi-view: photogrammetry + neural reconstruction (2025–2026)

**Source:** Tavily `pro` research + targeted search, 2026-05-25. This is
the path that *truly* scales with photo count, for when generative
image→3D isn't accurate enough. Cross-references
`../ar-survey/04-methodologies/findings.md` (SLAM / NeRF / 3DGS) and
`../ar-survey/05-tech-stack/findings.md` (capture tools).

---

## When to use this instead of a generative API

Use real multi-view photogrammetry / neural reconstruction when you need:
- **Metric accuracy** (real dimensions, not plausible shape).
- **Faithful texture** of the actual object, no hallucinated surfaces.
- **Full 360° coverage** including top/bottom.

Accept in exchange: **dozens to hundreds of photos**, careful capture,
minutes-to-hours of processing, and (mostly) **no single hosted-API
call** — it's a desktop pipeline or a scan app.

For our AR yard-décor use case this is **overkill** — but documented
here so the choice is deliberate.

---

## Family A — classical photogrammetry (SfM + MVS)

| Tool | License | Hosted API? | Notes |
|---|---|---|---|
| **COLMAP** | open source | no | Benchmark-topping SfM+MVS. CUDA GPU for dense MVS, ~32 GB RAM. Outputs dense point cloud, Poisson/Delaunay mesh, textured mesh + texture.png. CLI + GUI |
| **AliceVision / Meshroom** | open (MPL-2.0) | no | Node-graph GUI, NVIDIA GPU required for dense meshing. Exports OBJ/PLY/FBX/USD |
| **RealityScan / RealityCapture** (Epic) | commercial | no public API | Out-of-core → big projects on 16–32 GB RAM. Best alignment when neighbor overlap >60%. Can struggle on turntable sets |
| **Agisoft Metashape** | commercial | no | ≥3 photos per focal length to calibrate; aerial overlap 60% side / 80% forward. Broad export incl. glTF/GLB |
| **3DF Zephyr** | commercial | no | Prefers larger sensors (>1/2.3", pixel >2 µm) |

### Capture rules that matter (all SfM/MVS tools)
- **Overlap > 60%** between neighboring photos; every surface point seen
  in **≥3 images**.
- Capture **multi-tier passes** (top / middle / bottom) for full coverage
  of small/medium objects.
- **Avoid specular highlights**, keep illumination consistent.
- Add visual texture (markers/newspaper) for **textureless** objects.
- **Turntable caveat:** some tools (RealityCapture reported) mis-align
  turntable shots because the background appears static while the object
  rotates — Metashape handled the same set. Validate with a small test
  first, or mask the background.

### Common failure modes
- Textureless / low-feature surfaces → no features to match.
- Shiny / specular / transparent objects → reflections confuse matching
  (3DGS handles these better — see below).
- Low overlap → broken / disconnected geometry.

---

## Family B — neural reconstruction

(Detail largely from `../ar-survey/04-methodologies/findings.md`; the
fresh 2026 search adds the 3DGS→mesh tooling below.)

### NeRF
Instant-NGP, Nerfstudio, Zip-NeRF — multi-view photos/video → radiance
field → high-quality novel views; mesh extraction is secondary and
lossy. Great for view synthesis, weaker for clean editable meshes.

### 3D Gaussian Splatting (3DGS)
Multi-view → explicit Gaussians. Photorealistic, **handles reflections /
transparency better than photogrammetry** (it records how light behaves
in a volume rather than matching feature points). Raw output is `.ply`
splats — not a mesh.

### 3DGS → mesh (the bridge to our GLB pipeline)
- **SuGaR** — regularizes Gaussians onto surfaces during training, then
  Poisson reconstruction. Earliest approach; adds training overhead.
- **2DGS** — models Gaussians as elliptical disks, TSDF fusion → mesh.
- **PGSR** — adds single/multi-view geometric + consistency losses.
- **3DGS-to-PC** (ICCV-W 2025) — converts *any* trained 3DGS scene to a
  dense point cloud without retraining (more flexible than SuGaR/2DGS,
  which need surface-aligned training).
- These work best on indoor/dense-Gaussian scenes; object-scale results
  vary.

---

## Hosted scan apps (the realistic "no desktop" option)

These are mobile/cloud apps, mostly **not REST APIs** — but some expose
capture APIs (enterprise).

| App | Methods | Export | API | Pricing |
|---|---|---|---|---|
| **KIRI Engine** | photogrammetry, LiDAR, **3DGS + 3DGS→mesh** (claims first-to-market), featureless-object mode, turntable support | OBJ/FBX/STL/GLB/GLTF/USDZ/PLY/XYZ | **Yes** (offers API) | Free 3 exports/wk; Pro ~$6.99–9.99/mo (200 photos/scan, AI PBR) |
| **Polycam** | LiDAR, photo mode, Gaussian splat, AI captures | GLTF + 6 formats (Basic), point cloud (Business) | **Capture API** (contact sales) | Free (GLTF, ≤180 photos/capture); Basic ~$12.50/mo; Business ~$34/user/mo |
| **Luma AI** | video → 3DGS / NeRF | **PLY (splat) only — no mesh export** | Enterprise API | Free tier; **no longer actively updated** |
| **Scaniverse** | LiDAR + photogrammetry + 3DGS | mesh + splat | no public API | free |
| **RealityScan mobile** (Epic) | photogrammetry | mesh (OBJ/USDZ) | no | free; up to ~300 photos/scan |

**Relevant takeaways for us:**
- **KIRI Engine** is the standout: it has an API, does 3DGS→mesh, and
  exports **GLB/USDZ directly** — the formats our `ARStore` wants. If we
  ever want real-capture (not generative) assets in the catalog, KIRI's
  API is the closest hosted fit.
- **Polycam** has a capture API too (sales-gated) and exports GLTF.
- **Luma** is splat-only (no mesh) and sunsetting — avoid for our mesh
  pipeline.

---

## How this maps to our project

We don't need metric accuracy for AR-placed yard objects, so the
photogrammetry/neural path is **not** the primary recommendation. But:
- If a user wants **their actual object** (this specific fence, this
  exact planter) faithfully, a scan-app API (**KIRI**) is the route, and
  its GLB/USDZ output drops straight into `ARStore` with no conversion.
- The 3DGS→mesh tooling matters if we later ingest splat captures.
- Capture guidelines above are worth surfacing in any future "scan your
  own object" UX.

---

## References

1. COLMAP — https://colmap.github.io/tutorial.html ; https://colmap.org
2. Meshroom manual — https://meshroom-manual.readthedocs.io/
3. RealityScan align (overlap) — https://rshelp.capturingreality.com/en-US/appbasics/alignsettings.htm
4. Metashape manual — https://agisoft.com/pdf/metashape-pro_1_7_en.pdf
5. 3DF Zephyr capture — https://3dflow.net/technology/documents/photogrammetry-how-to-acquire-pictures
6. 3DGS-to-PC (ICCV-W 2025) — https://openaccess.thecvf.com/content/ICCV2025W/3D-VAST/papers/Stuart_3DGS-to-PC_3D_Gaussian_Splatting_to_Dense_Point_Clouds_ICCVW_2025_paper.pdf
7. KIRI 3DGS→mesh — https://www.kiriengine.app/blog/announcement/3dgs-to-mesh-convert-visualizations-to-obj
8. KIRI export formats — https://www.kiriengine.app/features/export-formats
9. Polycam pricing — https://poly.cam/pricing
10. Luma AI review (splat-only, sunsetting) — https://www.thefuture3d.com/software/luma-ai
11. Scanner app comparison 2026 — https://www.kiriengine.app/blog/Best_Free_3D_Scanner_Apps_2026
