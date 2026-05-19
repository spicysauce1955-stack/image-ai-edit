# Native Mobile AR SDKs — iOS & Android (2025–2026)

**Source:** Tavily `pro` research, 2026-05-18.

---

## TL;DR — Pick-by-use-case

| Use case | Recommended native stack |
|---|---|
| **Street-scale / city-scale AR** (outdoor anchored content) | **ARCore Geospatial API + Streetscape Geometry** — VPS-backed, requires Google Street View coverage, GCP API key, may need billing enabled |
| **Indoor room scanning, CAD pipelines** | **Apple RoomPlan + Object Capture + ARKit LiDAR** (LiDAR-only) |
| **High-quality AR video capture** | **ARKit 6+** (4K HDR @ 30fps during session, EXIF, manual exposure/WB) |
| **Shared multi-user AR** | **ARCore Cloud Anchors / Persistent Cloud Anchors** (Android-side native; no documented Apple-side equivalent) |
| **Photogrammetry → product AR** | **Apple Object Capture** (macOS full quality, iOS reduced detail, area mode since WWDC 2024) |
| **Spatial computing (Vision Pro)** | **RealityKit 4 + Reality Composer Pro + SwiftUI + visionOS 26** |

---

## Apple — ARKit / RealityKit / Reality Composer Pro / Object Capture / RoomPlan / visionOS

### Capabilities by component

**ARKit 6+** (iOS 16+):
- 4K HDR video capture (3840×2160 @ 30fps) *during* AR session
- EXIF metadata per AR frame
- Manual exposure / white-balance / focus control during session
- Expanded Location Anchors coverage
- Improved height estimation on iPhone 12+/iPad Pro
- People occlusion, single-camera motion capture (3D skeleton, ear landmarks)
- `ARPlaneExtent` for improved plane behavior

**RealityKit 4** (WWDC 2025):
- `AnchorEntity` exposes raw ARKit data
- `ManipulationComponent` for hand-based grabbing/manipulation
- `EnvironmentBlendingComponent` for occlusion blending
- `MeshInstancesComponent` for batched render efficiency
- Entity-component renderer, integrated with USD pipeline, physics, skeletal animation

**Reality Composer Pro:**
- Authoring app + Swift Package output
- Shader graph, audio mixing
- USD asset compilation pipeline, multi-platform output incl. visionOS

**Object Capture:**
- macOS: photo sets → USDZ at multiple detail levels, with camera pose output
- iOS: on-device reduced-detail reconstruction
- WWDC 2024 added "area mode" for whole rooms

**RoomPlan:**
- Swift API; camera + LiDAR → 3D floor plan
- Furniture detection, USD/USDZ export, built-in coaching UI, dollhouse view
- **LiDAR required**

**SceneKit:** In maintenance / effectively deprecated. Migrate new work to RealityKit + USDZ; `scntool` exists for `.scn → .usdz` conversion.

**visionOS 26** (Apple Vision Pro):
- Spatial widgets, `ViewAttachmentComponent`, `GestureComponent`, `PresentationComponent` (SwiftUI ↔ RealityKit)
- Vision Pro hardware: multi-cam array + LiDAR + R1 sensor-fusion chip
- Dev path: Xcode + SwiftUI + RealityKit + Reality Composer Pro (Unity also supported)

### Hardware gates (Apple)
- **LiDAR-only**: RoomPlan, full Depth API, optimal People Occlusion. iPhone 12 Pro+ Pro line, iPad Pro 2020+.
- **TrueDepth-only**: face tracking with front camera.
- **iOS 16+**: ARKit 6 4K capture + camera controls.
- **Apple Vision Pro**: visionOS-specific features.

### Pricing / licensing
- **Not present in evidence.** Apple's AR/RealityKit/RoomPlan/Object Capture SDKs ship with the Apple developer toolchain — implied free with Apple Developer Program but no explicit licensing terms surfaced in the research.

---

## Google — ARCore + Filament + SceneView (Android-native)

### Capabilities

**ARCore (recent):**
- Geospatial API + Streetscape Geometry + VPS (global, Street View-derived 3D point cloud)
- Anchor types: WGS84, Terrain, Rooftop
- Scene Semantics — classifies surfaces/objects (floor vs tabletop etc.)
- Depth API — 16-bit raw depth + confidence values
- Persistent Cloud Anchors — hosted on ARCore cloud endpoints
- Geospatial Depth (Depth + Streetscape) up to **65.535 m** depth range
- Augmented Faces, Augmented Images
- Unity 6 / AR Foundation 6 support; iOS via Swift Package Manager

**Filament:** Open-source PBR renderer, the engine under Sceneform; used cross-platform.

**Sceneform / SceneView:** Sceneform is archived; community-maintained **SceneView** (Kotlin, Filament-backed) is the active replacement. Repo: `https://github.com/sceneview/sceneview`.

**ML Kit + ARCore:** Camera feed → ML pipelines; Kotlin sample code exists for combining classification with AR overlay.

### Hardware gates (Android)
- ARCore device certification list at `https://developers.google.com/ar/devices`
- Depth API requires ARCore 1.31.0+ on supported devices
- Dual-camera stereo depth since ARCore 1.23
- Geospatial requires Google Street View VPS coverage in the target area

### Pricing / licensing
- **Conflicted evidence:**
  - Google blog post (Geospatial launch): "available at no cost"
  - SceneView Streetscape setup doc: "Geospatial API requires enabling ARCore API on GCP and **billing must be activated** to receive Streetscape geometries"
  - Cloud Anchors: subject to quotas and rate limits
- **Practical guidance:** treat as paid/quota-bound for production until verified with current Google docs. Confirm before launch.

### Privacy / terms
- ARCore terms require apps to disclose data handling.
- Geospatial / Cloud Anchors send camera + location data to Google.
- Some policy restrictions (e.g., COPPA-directed apps) on cloud features.

---

## Cross-platform shared AR — interoperability gap

- **Android side:** ARCore Cloud Anchors / Persistent Cloud Anchors are native; quota-limited.
- **Apple side:** No equivalent Apple-provided cross-platform anchor service in the evidence.
- **Implication:** For iOS↔Android shared AR you'll need either:
  - A third-party service (Niantic Lightship, Immersal, etc. — not covered in this research stream)
  - Custom server-side relative-pose alignment
  - Or constrain the experience to a single platform.

---

## Engine vs native trade-off

ARCore + ARKit are both reachable from **Unity (AR Foundation)** and **Unreal**. Engine route reduces platform friction, but **native-only features** (LiDAR-specific APIs, RoomPlan, Object Capture, 4K capture in AR session) still need native plugins. AR Foundation 6 + Unity 6 explicitly supported by ARCore as of recent updates.

---

## What the evidence didn't cover

- **Niantic Lightship ARDK** (native mobile) — VPS, meshing, semantic segmentation. Not surfaced.
- **Snapchat Camera Kit**, **Snap Lens Studio / Hologram** for native integration.
- **TikTok Effect House**.
- Apple's explicit privacy/cloud-processing statements per feature.
- Per-device benchmark numbers.

(All flagged for the synthesis step — likely need targeted searches.)

---

## References

1. ARKit overview — https://developer.apple.com/augmented-reality/arkit/
2. WWDC22 ARKit 6 — https://developer.apple.com/videos/play/wwdc2022/10126/
3. WWDC25 RealityKit 4 — https://developer.apple.com/videos/play/wwdc2025/287/
4. WWDC25 visionOS — https://developer.apple.com/videos/play/wwdc2025/274/
5. WWDC24 Object Capture (area mode) — https://developer.apple.com/br/videos/play/wwdc2024/10107/
6. RoomPlan — https://developer.apple.com/augmented-reality/roomplan/
7. Reality Composer Pro — https://developer.apple.com/videos/play/wwdc2023/10083/
8. ARKit supported video formats — https://developer.apple.com/documentation/arkit/arconfiguration/supportedvideoformats
9. visionOS 26 newsroom — https://apple.com/newsroom/2025/06/visionos-26-introduces-powerful-new-spatial-experiences-for-apple-vision-pro/
10. ARKit (AppleInsider tech reference) — https://appleinsider.com/inside/arkit
11. Awesome-RealityKit — https://github.com/divalue/Awesome-RealityKit
12. WWDC23 Object Capture — https://developer.apple.com/videos/play/wwdc2023/10191/
13. SceneKit deprecation analysis — https://dev.to/arshtechpro/wwdc-2025-scenekit-deprecation-and-realitykit-migration-a-comprehensive-guide-for-ios-developers-o26
14. ARCore — What's new — https://developers.google.com/ar/whatsnew-arcore
15. ARCore Geospatial — https://developers.google.com/ar/develop/geospatial
16. ARCore Cloud Anchors — https://developers.google.com/ar/develop/cloud-anchors
17. ARCore terms — https://developers.google.com/ar/develop/terms
18. ARCore privacy requirements — https://developers.google.com/ar/develop/privacy-requirements
19. ARCore ML integration — https://developers.google.com/ar/develop/machine-learning
20. ARCore device list — https://developers.google.com/ar/devices
21. Geospatial API quotas — https://developers.google.com/ar/develop/c/geospatial/api-usage-quota
22. SceneView Streetscape setup — https://github.com/sceneview/sceneview/blob/main/samples/android-demo/STREETSCAPE_SETUP.md
23. Sceneform docs — https://developers.google.com/sceneform
24. Filament for Android guide — https://victorbrandalise.com/a-guide-to-filament-for-android/
25. Geospatial launch blog — https://developers.googleblog.com/make-the-world-your-canvas-with-the-arcore-geospatial-api/
26. Streetscape Geometry + Rooftop codelab — https://developers.google.com/codelabs/arcore-streetscape-geometry-rooftop-anchors
27. ARCore runtime — https://developers.google.com/ar/develop/runtime
28. ARCore C reference — https://developers.google.com/ar/reference/c
