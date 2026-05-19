# Supporting Tech Stack for AR (2025–2026)

**Source:** Tavily `pro` research, 2026-05-18.

---

## TL;DR

- **Web / cross-engine asset format**: glTF 2.0 (GLB) with **KTX2/Basis textures** + **meshopt** (or Draco) geometry compression. Khronos `glTF-Compressor` tool automates the build step.
- **Apple-only delivery**: USDZ for Quick Look. Authored in Reality Composer Pro, packaged with RealityConverter / `usdzip`.
- **Browser ML**: ONNX Runtime Web with **WebGPU** execution provider is now the highest-perf path; MediaPipe Tasks for lightweight face/hand/pose; TFJS still relevant.
- **CDN/hosting**: Cloudflare R2 (no egress fees) or jsDelivr (open-source) for GLB delivery.
- **Loaders**: three.js GLTFLoader is the canonical pattern; register `DRACOLoader`, `KTX2Loader`, meshopt decoder before loading.
- **WebGPU caveat**: three.js WebGPURenderer KTX2/Basis support is still limited per community threads. Test on your target render path.

---

## 3D asset formats

### glTF 2.0 / GLB — the runtime web standard

- Khronos spec: `https://khronos.org/gltf/`
- PBR materials, scene hierarchy, extensions (KHR_*, EXT_*).
- **GLB** = single binary container. Use this for AR delivery.

### USDZ — the Apple delivery format

- Pixar USD packaged as **uncompressed zip** (.usdz).
- Apple Quick Look + RealityKit consume it directly.
- Author in Reality Composer Pro, package with `usdzip` or RealityConverter.
- USDZ is effectively read-only after packaging.

### FBX, OBJ — legacy interchange only

- **FBX**: proprietary Autodesk, use the FBX SDK to programmatically import/export. Useful for DCC interchange (rig + anim), not for runtime delivery.
- **OBJ**: ASCII, no hierarchy/skinning/animation. Quick interchange only.

### Geometry compression

| Codec | License | glTF ext | Use when |
|---|---|---|---|
| **Draco** | Apache-2.0 | `KHR_draco_mesh_compression` | Maximum geometry compression; mature ecosystem |
| **meshopt** | MIT | `EXT_meshopt_compression` | Fast decode + handles morph targets & numeric buffers; pair with brotli/gzip |

**Rule of thumb**: meshopt for runtime speed, Draco for max size reduction.

### Texture compression — KTX2 / Basis Universal

- KTX2 = Khronos container. Basis Universal = the supercompression codec inside it.
- Supports streaming mip levels + GPU-ready formats.
- Khronos `glTF-Compressor` tool converts texture bitmaps to KTX2 and writes the right extensions.
- **WebGPU caveat**: three.js WebGPURenderer support for KTX2/Basis is in progress — verify on your target.

### Build pipeline (recommended)

```
authoring tool → bake PBR
    → texture conversion to KTX2/Basis (glTF-Compressor)
    → geometry compression (meshopt or Draco)
    → write glTF extensions
    → supercompress (brotli/gzip)
    → CDN
```

---

## Authoring tools

| Tool | Role | License / cost | Notes |
|---|---|---|---|
| **Blender** | Modeling, UV, baking, glTF/USD export | GPL (source) / GPLv3+ (binaries) | Free, active. Blender 5.x line in 2025–2026 |
| **Maya** | High-end DCC, USD/FBX export | Commercial subscription | Industry standard for film/VFX |
| **3ds Max** | Polygon modeling, viz | Commercial | Often paired with Maya |
| **Substance 3D Painter** | PBR texturing, USD workflow | Adobe sub | Standard for material authoring |
| **Spline** | Web-based 3D design, GLTF/USDZ export | Freemium | Fast prototyping |
| **SketchUp** | Quick modeling, USDZ/OBJ/STL export | Commercial | Common in archviz / iPad AR prep |
| **Reality Composer Pro** | Apple AR authoring, USDZ | Free with Xcode | Shader graph, audio mixing, visionOS-ready |
| **Polycam, Luma AI, KIRI Engine** | 3D capture / Gaussian Splatting | Freemium (mobile apps) | **Not in evidence corpus** — verify pricing/licenses directly |

---

## 3D capture pipelines

### Photogrammetry — open source
- **Meshroom / AliceVision**: MPL-2.0, node-based pipeline. CUDA GPU recommended for full quality. Active releases.
- Repos: `https://alicevision.org/view/meshroom.html`, `https://github.com/alicevision/meshroom`.

### Photogrammetry — commercial
- **RealityCapture** (Epic): handles thousands of images, GPU/CUDA-accelerated, out-of-core processing. Pricing changed in late April 2025 (referenced).

### Apple
- **Object Capture** (macOS + iOS): photos → USDZ at multiple detail levels. Area mode (WWDC '24) extends to whole rooms. Covered fully in `02-mobile-ar/findings.md`.
- **RealityScan** (Epic + Apple ecosystem): mobile scanning app.

### Gaussian Splatting (newer)
- **Luma AI, Polycam, Scaniverse, KIRI Engine** — mobile capture apps producing 3DGS scenes. (Not in this evidence corpus — pricing and licensing need direct verification.)
- **gsplat / Mobile-GS** — research/tooling track demonstrating mobile-feasible 3DGS rendering.

### Typical capture-to-AR flow
1. Capture (many overlapping photos or 3DGS scan).
2. Process (alignment + meshing) on GPU-accelerated tool.
3. Retopologize + bake PBR textures.
4. Convert to glTF/GLB or USDZ.
5. Apply geometry + texture compression.
6. Test on target devices.

---

## AI / ML libraries usable in AR

### MediaPipe
- Repo: `https://github.com/google-ai-edge/mediapipe`
- **MediaPipe Tasks** (web): `@mediapipe/tasks-vision` npm package
- Solutions: face mesh, hands, pose, holistic, selfie segmentation
- Apache-2.0
- The default for "I need quick face/hand tracking in a browser or mobile app"

### ONNX Runtime Web
- Execution providers: **WASM, WebGL, WebGPU, WebNN**
- WebGPU EP gives the biggest perf jump for heavier models (segmentation, generative)
- Microsoft has actively promoted WebGPU + in-browser generative AI through the runtime
- Docs: `https://onnxruntime.ai/docs/tutorials/web/`

### TensorFlow.js
- Backends: WebGL, WASM, Node
- Mature, large model zoo
- BlazePose on MediaPipe runtime outperforms TFJS for pose tracking in published comparisons — pick based on the specific model

### transformers.js (Hugging Face)
- Not in evidence corpus but widely used — runs HF transformers via ONNX Runtime Web. Worth verifying current status if needed for text/vision-language tasks.

### Specific models

| Model | Use | Notes |
|---|---|---|
| **Segment Anything (SAM)** | Segmentation | Browser demos exist (sunu/SAM-in-Browser) but encoder is ~108MB and embedding takes ~30s–1min — initialization is heavy. Server inference often more practical |
| **MiDaS** (DPT_Large / Hybrid / small) | Monocular depth | Multiple speed/quality tiers |
| **Depth Anything V2** | Monocular depth | Newer; some variants have deployment restrictions |
| **YOLOv5 / YOLOv8** | Object detection | Exports to ONNX / CoreML / TFLite — on-device viable after quantization |
| **MediaPipe FaceMesh** | 468/478 face landmarks | The mobile/web default |

### On-device vs server inference (cheat-sheet)
- **On-device**: lightweight models, privacy-sensitive, offline-capable, sub-100ms latency required.
- **Server**: large models (SAM-class), GPU not always present on client, batch processing.
- **Hybrid**: client capability detection → use WebGPU+on-device when possible, fall back to server.

---

## Backend / asset delivery

### CDNs / hosting
- **Cloudflare R2** — object storage, **no egress fees**, CORS-friendly. Great for GLB hosting.
- **jsDelivr** — multi-CDN, free for open-source projects.
- **Custom CDN + signed URLs** if authorization required.

### Build tooling
- **Khronos glTF-Compressor**: KTX2/WebP conversion + extension writing.
- **glTF-Transform** (CLI + JS lib): the canonical glTF pipeline tool. **Watch for dependency deprecation warnings** in CI — community has reported some.

### Runtime loaders (three.js example)
```js
const gltfLoader = new GLTFLoader();
gltfLoader.setDRACOLoader(new DRACOLoader().setDecoderPath('/decoders/draco/'));
gltfLoader.setKTX2Loader(new KTX2Loader().setTranscoderPath('/decoders/basis/').detectSupport(renderer));
gltfLoader.setMeshoptDecoder(MeshoptDecoder);
```
- All major web engines (three.js, Babylon, PlayCanvas, model-viewer) follow this pattern.

---

## Persistence / cloud anchors / VPS

The evidence corpus for this stream was thin on this category. Cross-reference what's already documented in:
- `02-mobile-ar/findings.md` — ARCore Cloud Anchors / Persistent Cloud Anchors, Geospatial API
- `01-web-ar/findings.md` — Niantic Lightship VPS for Web
- `04-methodologies/findings.md` — Niantic VPS + Immersal documentation

**Known but not in this corpus**: **Azure Spatial Anchors was deprecated by Microsoft in Nov 2024** (retirement period). Verify status before planning anything new on Azure.

---

## Analytics for AR sessions

- **Gap.** No primary sources surfaced for AR-specific session telemetry / heatmap / anchor-success dashboards.
- Practical fallback: custom telemetry via standard tools (PostHog, Mixpanel, Datadog RUM) with custom events for anchor placement / tracking lost / FPS.
- Specialized vendors do exist (e.g., RealityScan analytics, 8th Wall historical dashboards) but pricing and current status need direct verification.

---

## WebGPU's impact on Web AR

### What's new
- **ONNX Runtime Web + WebGPU**: enables larger models in the browser at usable latency. Microsoft has demonstrated in-browser generative AI.
- **Three.js WebGPURenderer**: out of experimental but KTX2/Basis support has caveats — test before committing.
- **Babylon.js 8.0 (Apr 2025)**: added WebXR depth sensing + .usdz export.
- WebGPU on iOS Safari shipped in Safari 18 (verify current capability).

### Practical guidance
- **Detect capability at runtime**, don't assume.
- Provide a WebGL/WASM fallback path for ML inference.
- Test KTX2 texture loading on every target browser × renderer combo.

---

## Evidence gaps

- Luma AI, Polycam, KIRI Engine, Scaniverse — capture vendor specifics
- transformers.js current state
- Azure Spatial Anchors deprecation timeline (confirmed elsewhere as Nov 2024 retirement but not in this corpus)
- AR-specific analytics vendors
- WebXR-specific browser compatibility matrices for late 2025 / 2026

---

## References

1. glTF homepage — https://khronos.org/gltf/
2. EXT_meshopt_compression — https://gltf-transform.dev/modules/extensions/classes/EXTMeshoptCompression
3. meshoptimizer — https://github.com/zeux/meshoptimizer
4. Draco — https://github.com/google/draco
5. Khronos glTF-Compressor — https://khronos.org/blog/optimize-3d-assets-with-khronos-new-gltf-compressor-tool
6. KTX2 spec — https://github.khronos.org/KTX-Specification/ktxspec.v2.html
7. USDZ spec — https://openusd.org/release/spec_usdz.html
8. Library of Congress — USDZ — https://loc.gov/preservation/digital/formats/fdd/fdd000561.shtml
9. LoC — FBX — https://loc.gov/preservation/digital/formats/fdd/fdd000558.shtml
10. LoC — OBJ — https://loc.gov/preservation/digital/formats/fdd/fdd000507.shtml
11. Blender import/export docs — https://docs.blender.org/manual/en/2.93/files/import_export.html
12. Blender license — https://blender.org/about/license/
13. Blender releases — https://blender.org/download/releases/
14. SketchUp iPad import/export — https://help.sketchup.com/en/sketchup-ipad/importing-and-exporting
15. Substance Painter USD docs — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/universal-scene-description-usd
16. Spline — https://spline.design/3d-design
17. Meshroom — https://alicevision.org/view/meshroom.html
18. Meshroom GitHub — https://github.com/alicevision/meshroom
19. RealityCapture system reqs — https://proxpc.com/blogs/system-requirements-for-reality-capture-in-2025
20. Apple AR tools — https://developer.apple.com/augmented-reality/tools/
21. MediaPipe GitHub — https://github.com/google-ai-edge/mediapipe
22. @mediapipe/tasks-vision — https://jsdelivr.com/package/npm/@mediapipe/tasks-vision
23. ONNX Runtime Web — https://onnxruntime.ai/docs/tutorials/web/
24. ONNX Runtime Web WebGPU blog — https://opensource.microsoft.com/blog/2024/02/29/onnx-runtime-web-unleashes-generative-ai-in-the-browser-using-webgpu/
25. onnxruntime GitHub — https://github.com/microsoft/onnxruntime
26. TensorFlow.js — https://github.com/tensorflow/tfjs
27. BlazePose + TFJS — https://blog.tensorflow.org/2021/05/high-fidelity-pose-tracking-with-mediapipe-blazepose-and-tfjs.html
28. Segment Anything — https://github.com/facebookresearch/segment-anything
29. SAM in browser — https://github.com/sunu/SAM-in-Browser
30. MiDaS PyTorch hub — https://pytorch.org/hub/intelisl_midas_v2/
31. Depth Anything V2 in Roboflow — https://docs.roboflow.com/deploy/supported-models/depth-anything-v2
32. YOLOv5 — https://github.com/ultralytics/yolov5
33. glTF-Transform issue — https://github.com/donmccurdy/glTF-Transform/discussions/594
34. CDN comparison — https://blog.blazingcdn.com/en-us/jsdelivr-vs-unpkg-vs-cdnjs-best-free-cdn-for-open-source-projects
35. Cloudflare R2 — https://developers.cloudflare.com/r2/
36. three.js GLTFLoader — https://threejs.org/docs/pages/GLTFLoader.html
37. Vulkan KTX2 migration — https://docs.vulkan.org/tutorial/latest/15_GLTF_KTX2_Migration.html
38. three.js WebGPU + KTX2 discussion — https://discourse.threejs.org/t/webgpurenderer-compressed-texture-ktx2-basis/69362
