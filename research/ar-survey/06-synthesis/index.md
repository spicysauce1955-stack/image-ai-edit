# AR Survey — Synthesis & Recommendations

**Research date:** 2026-05-18
**Companion docs:**
- `../01-web-ar/findings.md`
- `../02-mobile-ar/findings.md`
- `../03-cross-platform/findings.md`
- `../04-methodologies/findings.md`
- `../05-tech-stack/findings.md`

---

## 1. Big picture — the 2025–2026 AR landscape

**Three major shifts in this window:**

1. **8th Wall hosted retired 28 Feb 2026.** The dominant commercial WebAR SLAM service is gone (open-sourced in part). Anyone planning new WebAR must pick a different stack or accept the open-source 8th Wall engine without hosting/Studio.
2. **Azure Spatial Anchors deprecated** (Microsoft retirement, Nov 2024). The major cross-platform cloud-anchor service is no longer a viable foundation. Niantic Lightship VPS + Immersal + ARCore Cloud Anchors / Geospatial fill that hole, but each has tradeoffs.
3. **WebGPU + on-device ML in browsers reaches usable performance.** ONNX Runtime Web's WebGPU EP plus mobile-feasible Gaussian Splatting (Mobile-GS) move work that previously required cloud GPUs onto the client.

Other context:
- SceneKit is deprecated; new Apple AR work targets RealityKit 4 + USD.
- ViroReact is back (acquired Jan 2025, active v2.54.0 Mar 2026) as the React Native default.
- ARKit added slanted plane alignment (WWDC 2024).
- ARCore Geospatial VPS billing/cost is ambiguous in Google's own docs — confirm before launch.
- Godot 4.6 (Jan 2026) is a serious open-source XR option for the first time.

---

## 2. Picking a stack by use case

### 2.1 "Show this product in AR" — product viewer, e-commerce

**Recommended:** `<model-viewer>` web component + glTF/GLB + USDZ.

- Single component handles WebXR → Scene Viewer (Android/ARCore) → Quick Look (iOS USDZ) fallback chain.
- Author in Blender or Substance Painter → export both GLB and USDZ variants.
- Compress with KTX2 textures + meshopt (or Draco).
- Host on Cloudflare R2 or jsDelivr.
- **Skip**: WebXR-only solutions (broken on iOS) or framework lock-in.

### 2.2 Image-anchored brand experience (poster → AR)

**Recommended (web):** MindAR (open source, MIT) + three.js + glTF.
**Recommended (commercial/managed):** Zappar Universal AR (Developer $12.99/mo) or 8th Wall engine (now open-source) self-hosted.

- MindAR image tracking is free, MIT, supports 52 face blendshapes if you also need filters.
- Use a high-contrast, non-repetitive target image (Vuforia star-rating guidance applies).

### 2.3 Face filters / avatar

**Recommended (web, open):** MindAR Face Tracking (MIT, 52 blendshapes).
**Recommended (web, scale):** Zappar or Snap Camera Kit (embed in your app).
**Recommended (mobile, native):** ARKit ARFaceAnchor (iOS) or MediaPipe FaceMesh (cross-platform).

If you're aiming for TikTok / Snap creator reach, build there directly — Effect House (TikTok-only by ToS) or Lens Studio + distribute via Camera Kit.

### 2.4 Place an object on a real surface — "IKEA Place"-style

**Recommended:**
- Cross-platform Unity build: **Unity 6 + AR Foundation 6.5 + ARKit XR Plug-in + ARCore XR Plug-in**.
- Native iOS: **ARKit + RealityKit 4 + USDZ**.
- Native Android: **ARCore + SceneView (Filament)**.
- React Native: **ViroReact (v2.54.0, MIT)**.

Plane detection + raycast + anchor + 3D model load is the canonical pattern. Skip Flutter unless Android-only (use `arcore_flutter_plus`).

### 2.5 Persistent AR shared across users (multi-player AR)

**Recommended (Android-native):** ARCore Persistent Cloud Anchors.
**Recommended (cross-platform):** **Niantic Lightship ARDK 4.x + AR Foundation + Lightship VPS**.

- Lightship multiplayer is free <50k MAU.
- ARCore Cloud Anchors are Android-only-native; for cross-platform shared experiences, Lightship is the documented path.
- **Avoid**: Azure Spatial Anchors (retired).

### 2.6 Outdoor / city-scale AR

**Recommended:** ARCore Geospatial API + Streetscape Geometry (anchor types: WGS84, Terrain, Rooftop). Requires GCP API key + Street View VPS coverage. **Confirm billing model** (evidence is ambiguous).

**Alternatives:**
- Niantic Lightship VPS at activated locations.
- Immersal for stadium / venue-scale.

### 2.7 Indoor room scanning / measurement / CAD

**Recommended (Apple, LiDAR-only):** **ARKit + RoomPlan + Object Capture** → USDZ pipeline. Best in class.
**Recommended (Android):** ARCore Depth API + SceneView, but quality is hardware-dependent.

If you need cross-platform, Niantic Lightship's cross-platform meshing (works without LiDAR) is the documented option.

### 2.8 3D capture of objects/scenes for AR content

**Recommended (Apple users):** **Object Capture** (macOS for full quality, iOS reduced detail, area mode for rooms since WWDC '24).
**Recommended (commercial/mobile, Gaussian Splatting):** **Polycam / Luma AI / Scaniverse / KIRI Engine**. Verify pricing directly — vendor docs weren't in the research corpus.
**Recommended (open source):** **Meshroom / AliceVision** (CUDA-accelerated).

### 2.9 Passthrough AR on headsets (Quest 3, Vision Pro)

**Recommended:**
- Cross-platform → Unity AR Foundation 6.5 + Meta OpenXR + visionOS XR Plug-in.
- Quest-native → Unreal + MetaXR Horizon Integration SDK (handheld AR ≠ OpenXR in UE, so plan accordingly).
- Apple-native → RealityKit 4 + Reality Composer Pro + visionOS 26 SwiftUI components.
- **Open-source headset XR**: **Godot 4.6** — passthrough + OpenXR 1.1 + Spatial Entities, Khronos-loader APK for single-binary multi-device.

### 2.10 ML-heavy AR (segmentation, depth, generative)

**Recommended (browser):** ONNX Runtime Web with **WebGPU** execution provider. Fall back to WASM/WebGL.
**Recommended (mobile, on-device):** MediaPipe Tasks (face/hand/pose/segmentation), or model conversion to CoreML / TFLite (YOLO, MiDaS variants).
**Hybrid:** ship lightweight tracking on-device; offload SAM-class segmentation or NeRF/3DGS rendering to server/edge.

---

## 3. Master comparison matrix

| Framework | Platform | Tracking | License | Status | Best for |
|---|---|---|---|---|---|
| **WebXR Device API** | Browsers | VIO + opt-in plane/image | W3C standard | Active; iOS partial | Foundation for custom web AR |
| **AR.js** | Web (Android Chrome + iOS Safari) | Marker, NFT image, GPS | MIT | Active 3.4.x | Lightweight web markers |
| **MindAR** | Web | Image + face (52 blendshapes) | MIT | Active | Open-source brand AR + filters |
| **A-Frame** | Web | Provider-based | MIT | Active 1.7.1 | Declarative scenes on three.js |
| **three.js + WebXR** | Web | WebXR + WebGL/WebGPU | MIT | Active | Custom web AR |
| **Babylon.js + WebXR** | Web | WebXR + WebGPU + .usdz export (8.0) | Apache-style | Active 8.0 (Apr 2025) | Web AR with depth-sensing |
| **Google model-viewer** | Web | WebXR → Scene Viewer → Quick Look | Apache-2.0 | Active | Product viewer / e-commerce |
| **8th Wall** | Web | SLAM + image + face | Engine OSS; SLAM binary | **Hosted retired Feb 2026** | Self-hosted SLAM WebAR |
| **Niantic Lightship VPS (Web)** | Web | Cloud VPS | Commercial | Active | Cm-class outdoor WebAR |
| **Zappar Universal AR** | Web + Unity | Face/image/world | Subscription ($12.99–$315/mo) | Active | Branded multi-engine SDK |
| **Wonderland Engine** | Web | SLAM/marker/image/face/body | Free <$120k/yr + 10% royalty | Active 1.5.3 | WASM web AR engine |
| **PlayCanvas** | Web | WebXR + image + plane | Tiered (free/$15/$50) | Active | Hosted WebGL/WebGPU AR |
| **ARKit / RealityKit 4** | iOS / visionOS | VIO + LiDAR + face/people/body | Apple dev (free with program) | Active (WWDC25 RK4) | Best Apple AR + Vision Pro |
| **ARCore** | Android (+ iOS Swift Pkg Mgr) | VIO + Geospatial + Depth + Cloud Anchors | Free + GCP quotas | Active | Android + city-scale outdoor |
| **Apple RoomPlan** | iOS (LiDAR) | LiDAR scene reconstruction | Apple dev | Active | Indoor room capture |
| **Apple Object Capture** | macOS / iOS | Photogrammetry → USDZ | Apple dev | Active (area mode WWDC24) | Photogrammetry pipeline |
| **Unity AR Foundation 6.5** | iOS, Android, visionOS, Quest, HoloLens | Provider-abstracted | Unity license | Active | Industry-standard cross-platform |
| **Unreal Engine 5.x** | iOS/Android handheld + HMDs (OpenXR) | ARKit/ARCore + OpenXR | UE EULA, 5% royalty | Active | High-fidelity / HMD |
| **Niantic Lightship ARDK 4.x** | iOS, Android (on AR Foundation) | Meshing + SemSeg + VPS + Multiplayer | Free core; multiplayer free <50k MAU | Active | Cross-platform persistent + multiplayer AR |
| **ViroReact** | iOS / Android / Meta Horizon OS | ARKit + ARCore | MIT | Active 2.54 (Mar 2026) | React Native AR |
| **Flutter AR (ar_flutter_plugin)** | iOS + Android | ARKit + ARCore | — | **Stale** (Nov 2022) | Not recommended |
| **Flutter arcore_flutter_plus** | Android only | ARCore | MIT | Active | Flutter + Android-only |
| **Godot 4.6** | OpenXR HMDs + Quest + WebXR; ARCore plugin near completion | OpenXR 1.1 + Spatial Entities | MIT | Active (Jan 2026) | Open-source XR |
| **Snap Camera Kit** | iOS, Android, Web; Unity sample | Snap Lenses | Camera Kit ToS | Active | Embed Snap lenses in your app |
| **TikTok Effect House** | TikTok only | Native effects | Effect House ToS | Active 5.x | TikTok creators only |

---

## 4. Default stack recommendations

### "I'm building a web AR experience and I just want defaults":
- **Framework**: three.js + WebXR (or A-Frame if you prefer declarative).
- **Assets**: glTF/GLB + KTX2 textures + meshopt.
- **Image tracking**: MindAR (open source).
- **Face tracking**: MindAR or MediaPipe FaceMesh.
- **ML**: MediaPipe Tasks for vision; ONNX Runtime Web (WebGPU) for heavier models.
- **Hosting**: Cloudflare R2 + Cloudflare CDN.
- **iOS fallback**: USDZ via Quick Look (use model-viewer as the entry component).

### "I'm building a native iOS AR app":
- ARKit + RealityKit 4 + Reality Composer Pro + USDZ.
- Targeted iOS 17+ for RealityKit 4 features.
- LiDAR-gated features fenced by device capability checks.

### "I'm building a native Android AR app":
- ARCore + SceneView (Kotlin, Filament-backed).
- For city-scale: ARCore Geospatial + Streetscape Geometry — verify billing model in 2026.

### "I'm building cross-platform iOS + Android AR":
- Unity 6 + AR Foundation 6.5 + ARKit + ARCore + Meta OpenXR XR Plug-ins.
- Add Niantic Lightship ARDK 4.x if you need cross-platform meshing / semantic segmentation / VPS / multiplayer.

### "I'm building React Native AR":
- ViroReact (v2.54+, MIT). Don't try `expo-three-ar` — it's unsupported.

### "I'm building open-source XR for Quest passthrough":
- Godot 4.6 with OpenXR 1.1 + Spatial Entities. Khronos-loader APK simplifies multi-device builds.

### "I'm capturing 3D content to put in AR":
- Apple ecosystem: Object Capture (area mode for rooms).
- Cross-platform: Polycam or Luma AI (Gaussian Splatting), or Meshroom (open source, CUDA).
- Export glTF/GLB for web, USDZ for Apple.

---

## 5. Open questions / things to verify before committing

1. **ARCore Geospatial pricing in 2026** — Google's docs conflict (free vs billing-required). Confirm with current GCP billing console.
2. **Niantic Lightship VPS pricing tiers** — sales-gated; not in public docs.
3. **8th Wall open-source roadmap** — what's truly open vs binary-only SLAM. Re-check at `8thwall.org`.
4. **Azure Spatial Anchors final retirement date** — known-deprecated but Microsoft retirement timelines vary.
5. **WebGPU iOS Safari support** — moving target. Verify on Safari 18+.
6. **Capture vendor pricing (Polycam, Luma AI, KIRI, Scaniverse)** — verify directly; not in our corpus.
7. **transformers.js current status for HF models in browser** — verify if needed.

---

## 6. Things to skip / avoid

- **Azure Spatial Anchors** — deprecated.
- **Expo `expo-three-ar`** — unsupported; bare-workflow or ViroReact.
- **SceneKit** for new Apple work — use RealityKit + USD.
- **`ar_flutter_plugin`** — last release Nov 2022; stale.
- **Sceneform** (Google) — archived; use community SceneView.
- **8th Wall hosted Studio** — retired Feb 2026.
- **Variant / Onirix / Awe.js / Rocketbox** — no current evidence of active maintenance (verify if you care).

---

## 7. Reading order for someone new to this survey

1. This document (`06-synthesis/index.md`) — overview + matrix.
2. `01-web-ar/findings.md` if web is your target.
3. `02-mobile-ar/findings.md` if iOS/Android native is your target.
4. `03-cross-platform/findings.md` if multi-platform is the goal.
5. `04-methodologies/findings.md` for vocabulary on SLAM, anchors, tracking, NeRF/3DGS.
6. `05-tech-stack/findings.md` for assets, ML libs, build pipeline, hosting.
