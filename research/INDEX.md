# Research Index

Last updated: 2026-05-18

This directory holds three pieces of AR research, each with a distinct angle. Start with whichever matches your current question.

---

## 1. `ar-survey/` — broad survey of Web + Mobile AR (2025–2026)

**Use when:** picking a stack for a new AR project; comparing frameworks; needing a vocabulary of methodologies; understanding the 2025–2026 landscape shifts.

| File | Lines | Covers |
|---|---:|---|
| [`ar-survey/README.md`](ar-survey/README.md) | 18 | Layout + scope |
| [`ar-survey/process-log.md`](ar-survey/process-log.md) | 73 | How the research was conducted |
| [`ar-survey/01-web-ar/findings.md`](ar-survey/01-web-ar/findings.md) | 147 | WebXR, AR.js, A-Frame, MindAR, 8th Wall, Niantic VPS Web, Zappar, model-viewer, three.js, Babylon, Needle, PlayCanvas, Wonderland |
| [`ar-survey/02-mobile-ar/findings.md`](ar-survey/02-mobile-ar/findings.md) | 171 | ARKit 6+/RealityKit 4, RoomPlan, Object Capture, visionOS 26, ARCore Geospatial/Streetscape/Cloud Anchors/Depth, Filament, SceneView |
| [`ar-survey/03-cross-platform/findings.md`](ar-survey/03-cross-platform/findings.md) | 162 | Unity AR Foundation 6.5, Unreal 5.x, Niantic Lightship ARDK 4.x, ViroReact (revived), Flutter, Godot 4.6, Snap Camera Kit, TikTok Effect House |
| [`ar-survey/04-methodologies/findings.md`](ar-survey/04-methodologies/findings.md) | 218 | VI-SLAM, marker/NFT/markerless tracking, plane detection, monocular depth vs LiDAR/ToF, occlusion, light estimation, MediaPipe face/hand/body, VPS, mesh reconstruction, semantic segmentation, NeRF & 3D Gaussian Splatting, passthrough vs phone AR |
| [`ar-survey/05-tech-stack/findings.md`](ar-survey/05-tech-stack/findings.md) | 254 | glTF/USDZ/FBX/OBJ, Draco vs meshopt, KTX2/Basis, authoring tools, photogrammetry (Meshroom/RealityCapture/Object Capture), MediaPipe/ONNX Runtime Web/TFJS, SAM/MiDaS/Depth Anything/YOLO, CDNs, glTF-Transform, WebGPU impact |
| [`ar-survey/06-synthesis/index.md`](ar-survey/06-synthesis/index.md) | 214 | **Master comparison matrix + per-use-case recommended stacks** — read this first if you're picking tech |

**Top-of-mind findings (Synthesis doc has the full list):**
- 8th Wall hosted retired 28 Feb 2026 — engine partly open-sourced.
- Azure Spatial Anchors deprecated (Nov 2024).
- ARCore Geospatial billing is ambiguous in Google's own docs — verify before launching.
- ViroReact alive again (acquired Jan 2025, v2.54 Mar 2026).
- WebGPU + ONNX Runtime Web now usable for heavier in-browser ML.
- SceneKit deprecated; `expo-three-ar` unsupported; `ar_flutter_plugin` stale.

---

## 2. `ar-yard-objects-research.md` — narrow study, 216 lines

**Use when:** specifically building an AR app for placing yard objects (fences, pools, landscaping) in the real world; looking for the open-source building blocks.

**Sections:** Foundational AR frameworks rated for yard-object use; specialized/demo projects (CamAR, Google AR Drawing, ARKit-CoreLocation); ARCore API mapping (plane detection, scene semantics, geospatial API); tech-stack recommendation; key challenges (outdoor lighting, scale, persistence, occlusion).

**Conclusion in the doc:** No dedicated open-source project exists for yard-object AR placement — closest commercial precedents are IKEA Place / Houzz. SceneView (Kotlin/Filament + Swift/RealityKit) is the strongest cross-platform open-source starting point.

---

## 3. `ar-manuals-introductions-guides.md` — learning-path index, 355 lines

**Use when:** onboarding to AR development; looking for official docs, design guidelines, code samples, and a phased learning plan.

**Sections:**
1. Official platform docs (ARCore, ARKit, AR Foundation, SceneView, WebXR)
2. Web-based AR documentation
3. Curated resource lists (Awesome-ARKit 8k★, Awesome-ARCore, Google AR Codelabs)
4. Design guides (Google AR design guidelines, Apple AR Human Interface Guidelines)
5. Open-source samples (AR Foundation Samples, SceneView samples, ARCore samples, CamAR, ARKit-CoreLocation 5.5k★)
6. Phased learning path (Phase 1 fundamentals 1–2 wk, Phase 2 platform deep-dive 2–3 wk, Phase 3 implementation 3–6 wk)
7. Technical-concepts glossary
8. Essential URLs quick reference

---

## How the three relate

```
ar-manuals-introductions-guides.md      → "I'm new to AR, where do I start?"
                ↓
ar-survey/                              → "What's the current landscape and which stack do I pick?"
                ↓
ar-yard-objects-research.md             → "I'm building yard-object AR specifically"
```

`ar-survey/` is the most current and broadest. The two older files complement it: the manuals doc has the onboarding angle and curated resource lists; the yard-objects doc has the domain-specific lens. Treat them as still-useful satellites around the survey.

---

## File totals

```
ar-manuals-introductions-guides.md         355 lines
ar-yard-objects-research.md                216 lines
ar-survey/  (8 files)                    1,257 lines
                                         -----------
                                         1,828 lines total
```
