# Cross-Platform AR Frameworks (2024–2026)

**Source:** Tavily `pro` research, 2026-05-18.

---

## TL;DR

- **Unity AR Foundation** — the industry default. AR Foundation 6.5 + Unity 6.x. *Abstraction-only* — you must pair it with a provider plug-in (ARCore, ARKit, OpenXR, visionOS, Meta OpenXR). Used as the base by Niantic Lightship.
- **Unreal Engine 5.x** — Handheld AR via ARKit/ARCore; HMD AR via OpenXR. **OpenXR in Unreal does NOT cover handheld AR** — that's a frequent surprise. UE 5.4.4 fixed Android 14 target SDK publishing.
- **Niantic Lightship ARDK 3.x** — Unity SDK on top of AR Foundation. Adds meshing (cross-platform, non-LiDAR), semantic segmentation, occlusion, VPS, multiplayer (Unity Netcode). **3.x repos deprecated** — go to `nianticspatial` org for 4.x+. Multiplayer free <50k MAU.
- **ViroReact** — Acquired Jan 2025 by Morrow Digital, now under ReactVision org. Active (v2.54.0 Mar 2026). MIT. iOS/Android/Meta Horizon OS, Expo + RN CLI.
- **Expo `expo-three-ar`** — **No longer supported**; Expo Go removed built-in AR. Bare workflow only.
- **Flutter** — `ar_flutter_plugin` stuck at 0.7.3 from Nov 2022 (stale). `arcore_flutter_plus` actively maintained but **Android-only**.
- **Godot 4.6** (Jan 2026) — Real progress. OpenXR 1.1, Spatial Entities (anchors + planes), passthrough, Khronos-loader APK for multi-device builds. ARCore plugin near completion (community).
- **Snap Camera Kit** — Cross-platform SDK (iOS/Android/web) for embedding Lens Studio lenses into your app. Unity-as-Library sample exists.
- **TikTok Effect House** — Locked to TikTok platform per terms; not usable in third-party apps.

---

## Comparative matrix

| Framework | Platforms | License | Status | Best for |
|---|---|---|---|---|
| **Unity AR Foundation 6.5** | iOS, Android, visionOS, Quest (Meta OpenXR), HoloLens 2 | Unity license | Active, GA | Mainline cross-platform AR; production |
| **Unreal Engine 5.x** | iOS/Android handheld AR; HMDs via OpenXR | UE EULA, 5% royalty | Active; 5.4.4 hotfix for Android 14 | High-fidelity AR, HMD passthrough |
| **Niantic Lightship ARDK 4.x** | iOS, Android (on AR Foundation) | Free core APIs; multiplayer free <50k MAU | Active under `nianticspatial` org | VPS, meshing, semantic segmentation |
| **ViroReact (v2.54)** | iOS, Android, Meta Horizon OS | MIT | Active (Mar 2026 release) | React Native AR apps |
| **expo-three-ar** | iOS only, Expo | — | **Deprecated** (Expo Go AR removed) | — (avoid) |
| **ar_flutter_plugin** | iOS + Android | — | Stale (last 0.7.3, Nov 2022) | Legacy, not recommended |
| **arcore_flutter_plus** | Android only | MIT | Active | Flutter Android-only AR |
| **Capacitor AR plugins** | — | — | No evidence found | (gap) |
| **Cordova AR plugins** (csAR, Augment) | iOS/Android via Cordova | Varies | Legacy toolchain | Legacy hybrid apps |
| **Godot 4.6** | OpenXR HMDs + Quest passthrough; WebXR; ARCore plugin in progress | MIT | Active, accelerating (Khronos + W4 funded) | Open-source XR / passthrough |
| **Snap Camera Kit** | iOS, Android, web; Unity sample | Camera Kit ToS (Snap approval) | Active LTS | Embedding Snap Lenses in your app |
| **TikTok Effect House** | TikTok only | Effect House ToS | Active (5.x series) | TikTok creators only |

---

## Per-framework notes

### Unity AR Foundation 6.5
- **AR Foundation is an abstraction layer**, not a runtime. You install AR Foundation + at least one provider plug-in:
  - Google ARCore XR Plug-in (Android)
  - Apple ARKit XR Plug-in (iOS)
  - Apple visionOS XR Plug-in
  - Unity OpenXR: Meta (Quest)
  - Unity OpenXR: Android XR
  - OpenXR Plug-in (HoloLens 2)
- Exposes `ARSubsystems` (planes, anchors, raycast, image tracking, face, body, meshing — exact subsystem coverage varies by provider). Subsystems materialize as Unity GameObjects/MonoBehaviours.
- Samples: `Unity-Technologies/arfoundation-samples` (active). `arfoundation-demos` archived.
- **Major caveat**: feature parity is **per provider**, not per AR Foundation version. Always check the provider's capability matrix.

### Unreal Engine 5.x
- Two AR paths:
  - **Handheld** AR: ARKit / ARCore. Unreal has a "Handheld AR Blueprint" template.
  - **HMD** AR: OpenXR (Meta XR / VIVE OpenXR / Snapdragon Spaces).
- **OpenXR in Unreal is HMD-focused** — there's no OpenXR handheld AR path. So cross-platform AR via Unreal still mixes ARKit/ARCore + OpenXR.
- Vendor OpenXR plugins (Meta XR) can interfere with other PC VR headsets — known interop issue.
- UE 5.4 released, 5.4.4 hotfix handled Android 14 / TargetSDK 34 publishing.
- Meta Horizon Integration SDK 201.0 released Apr 15, 2026 (passthrough color rendering fixes).

### Niantic Lightship ARDK
- Sits on top of Unity AR Foundation.
- Features: real-time meshing, semantic segmentation, occlusion, Lightship Maps (VPS), multiplayer (Unity Netcode).
- Meshing + semantic segmentation are **cross-platform** (works on non-LiDAR Android) — that's the differentiator vs ARKit-only equivalents.
- 3.0 announced free core APIs (semseg, meshing). Multiplayer: free <50k MAU.
- **Migration alert**: 3.x repos under `niantic-lightship` are deprecated. ARDK 4.x lives at `nianticspatial.com/docs/nsdk/`.
- Production case: Historic Royal Palaces, Tower of London AR flower experience.

### ViroReact
- Open-sourced 2019 by Viro Media, community-maintained, **Jan 2025 acquired by Morrow Digital**, **ReactVision spin-off late 2025** to continue XR work.
- Supports iOS (ARKit), Android (ARCore), Meta Horizon OS.
- Works with both React Native CLI and Expo.
- v2.54.0 (Mar 31, 2026): improved image marker handling, plane detection, shader modifier system, depth sensor access. **Active.**
- MIT licensed.

### Expo AR / expo-three-ar
- iOS-only historically; integrated three.js with ARKit.
- **Built-in Expo Go AR support has been removed** — `expo-three-ar` is no longer supported.
- For RN AR in 2025–2026: ViroReact is the documented path.

### Flutter AR
- `ar_flutter_plugin`: iOS + Android, but **last release 0.7.3 in Nov 2022**. Open issues backlog, stale.
- `arcore_flutter_plus`: Android-only, MIT, supports `.glb`/`.sfb`, actively published. Successor to `arcore_flutter_plugin`.
- **Gap**: no actively-maintained cross-platform Flutter AR plugin in the evidence.

### Capacitor / Cordova
- **No Capacitor AR plugin evidence found.** Gap.
- Cordova: `csAR` (overlay-only), Augment Cordova (real devices only). Legacy toolchain.

### Godot Engine
- 4.2+: passthrough for OpenXR + WebXR.
- 4.6 (Jan 26, 2026): OpenXR 1.1, **Spatial Entities** (anchors + plane detection), frame synthesis with depth buffer, Khronos-loader APK for shipping a single APK to multiple devices.
- Funded by Meta (via W4 Games) and Khronos.
- ARCore plugin community-maintained, "near completion."
- Most exciting open-source XR engine trajectory right now.

### Snapchat
- **Lens Studio**: 375k+ registered creators, 4M+ Lenses, trillions of views. Face Lenses + World Lenses + ML asset library.
- **Camera Kit**: embed Lens Studio lenses in your own iOS/Android/web app. Cross-platform SDK with LTS releases.
- Unity sample: `Snapchat/camera-kit-unity-sample` — Unity-as-Library bridge, no native Swift/Kotlin code required.
- Camera Kit ToS (updated Feb 13, 2026) requires Snap approval and can be revoked.

### TikTok Effect House
- Locked to TikTok per ToS — **cannot embed in third-party apps**.
- Frequent releases (5.x series 2025–2026), built-in console for scripting since v5.0.0.
- Has a Branded Effects monetization program.

---

## Known cross-cutting pitfalls

- **AR Foundation parity is per provider.** Features marked as supported by AR Foundation may not be implemented by the provider plug-in for your target.
- **Unreal handheld AR ≠ OpenXR.** Plan separate codepaths.
- **Vendor OpenXR plugins fight each other.** Meta XR plug-in can block other PC VR runtimes; test on intended hardware.
- **WebAR landscape upheaval**: 8th Wall hosted platform retired Feb 28, 2026 — engine partly open-sourced (binary SLAM under proprietary license; framework MIT). Re-evaluate any 8th Wall-based plans.
- **Expo Go's AR removal** has stranded most Expo-managed AR projects. Bare workflow or ViroReact are the documented paths.

---

## Evidence gaps

- Capacitor (Ionic) modern AR plugins
- Kotlin Multiplatform (KMP) AR
- .NET MAUI AR
- `react-native-arkit` current state
- Full Unity AR Foundation subsystem support matrix per provider
- Quantitative community metrics (stars/contributors/issues) across most projects

---

## References

1. AR Foundation 6.5 install — https://docs.unity3d.com/Packages/com.unity.xr.arfoundation@6.5/manual/project-setup/install-arfoundation.html
2. arfoundation-samples — https://github.com/Unity-Technologies/arfoundation-samples
3. Lightship 3 announce — https://nianticlabs.com/news/lightship3/
4. Niantic Spatial SDK docs — https://nianticspatial.com/docs/nsdk/
5. Lightship multiplayer launch — https://nianticlabs.com/news/lightshiplaunch/
6. ARDK UPM repo (deprecated) — https://github.com/niantic-lightship/ardk-upm
7. Lens Studio overview — https://developers.snap.com/lens-studio/overview/getting-started/lens-studio-overview
8. Camera Kit home — https://developers.snap.com/camera-kit/home
9. Camera Kit Unity sample — https://github.com/Snapchat/camera-kit-unity-sample
10. Effect House releases — https://effecthouse.tiktok.com/latest/release-notes-latest
11. Meta Unreal integration — https://developers.meta.com/horizon/downloads/package/unreal-engine-5-integration/
12. UE AR overview — https://dev.epicgames.com/documentation/unreal-engine/augmented-reality-overview-in-unreal-engine
13. UE supported XR devices — https://dev.epicgames.com/documentation/unreal-engine/supported-xr-devices-in-unreal-engine
14. UE 5.4 release thread — https://forums.unrealengine.com/t/unreal-engine-5-4-released/1817064
15. UE 5.4.4 hotfix — https://forums.unrealengine.com/t/5-4-4-hotfix-released/1993894
16. ar_flutter_plugin — https://fluttergems.dev/packages/ar_flutter_plugin/
17. arcore_flutter_plus — https://pub.dev/packages/arcore_flutter_plus
18. ViroReact — https://github.com/ReactVision/viro
19. ViroReact releases — https://github.com/ReactVision/viro/releases
20. expo-three-ar — https://github.com/expo/expo-three-ar
21. csAR Cordova — https://github.com/tjwoon/csAR
22. Augment Cordova SDK — https://developers.augment.com/cordova-sdk
23. Godot XR Nov 2024 — https://godotengine.org/article/godot-xr-community-nov-2024/
24. Godot XR Oct 2024 — https://godotengine.org/article/godot-xr-update-oct-2024/
25. Godot VR overview — https://ziva.sh/blogs/godot-vr
26. 8th Wall open source — https://8thwall.org/docs/open-source
27. Babylon 8.0 release — https://blogs.windows.com/windowsdeveloper/2025/04/03/part-3-babylon-js-8-0-gltf-usdz-and-webxr-advancements/
28. UE OpenXR interop issue — https://uploadvr.com/metas-unity-unreal-openxr-sdks-block-other-pc-vr-headsets/
