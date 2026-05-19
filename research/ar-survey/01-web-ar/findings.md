# Web AR — Frameworks, Libraries & Hosting (2025–2026)

**Source:** Tavily `pro` research, 2026-05-18. All citations resolve to URLs in the References section.

---

## TL;DR

- **Platform baseline:** WebXR Device API (W3C) — strong on Chrome/Edge/Opera/Samsung Internet/Meta Quest Browser, partial/experimental on Safari/Vision Pro (visionOS 2+ improved), limited on Firefox. Plane-detection/image-tracking are opt-in features and depend on device-native support.
- **Open-source, client-only:** AR.js (markers + image + GPS, lightweight), MindAR (image + face, MIT, ES modules since 1.2.5), A-Frame (declarative wrapper, uses three.js, integrates AR.js/8th Wall/Zappar), three.js + WebXRManager, Babylon.js + WebXR.
- **Commercial / hybrid:** Zappar Universal AR ($12.99/mo Developer → Pro $315/mo → Enterprise; SDKs for A-Frame/three.js/Babylon/PlayCanvas/Unity), Niantic Lightship VPS for Web (cloud localization, integrates with 8th Wall), Wonderland Engine (free under $120k revenue, 10% royalty above), PlayCanvas (Free/$15/$50 tiers), Needle Engine (pricing not stated in evidence).
- **Big 2026 event:** 8th Wall's hosted platform retired 28 Feb 2026; tooling/engine released for free/open use. Published experiences keep running until Feb 2027. Major shift in the WebAR commercial landscape.
- **Model-viewer**: Google web component, fallback chain — WebXR → Scene Viewer (ARCore) on Android → Quick Look (USDZ) on iOS. Best for "show this product in AR" use cases.

---

## Comparative Matrix

| Project | Tracking | Browser Support | License / Price | Status (2025–2026) |
|---|---|---|---|---|
| **WebXR Device API** | 6DoF + opt-in image-tracking, plane-detection (device-dependent) | Chrome/Edge/Opera/Samsung; Quest Browser strong; Safari/Vision Pro experimental → improved in visionOS 2+; Firefox limited | W3C open standard | Active spec work |
| **AR.js** | Marker, image (NFT), GPS/location | Android Chrome + iOS Safari (HTTPS required) | MIT (artoolkit5-js LGPLv3) | Active, 3.4.x line |
| **A-Frame** | Depends on provider (AR.js / 8th Wall / Zappar) | Wherever WebXR or provider works | Open source | Active, 1.7.1 (Apr 2025) |
| **MindAR** | Image tracking + face (52 blendshapes) | Modern mobile browsers (HTTPS) | MIT | Active, ES modules since 1.2.5 |
| **8th Wall** | SLAM world tracking, image targets, face, sky segmentation | Cross-platform mobile browsers | **Hosted platform retired 28 Feb 2026** — engine + tools now open / free | Existing experiences run until Feb 2027 |
| **Niantic Lightship VPS for Web** | Cloud-based Visual Positioning (cm-level) | Integrated via 8th Wall | Commercial (Niantic) | Active; integration docs published |
| **Zappar / ZapWorks Universal AR** | Face, image, world tracking | Chrome Android + Safari iOS 11.3+ | Developer $12.99/mo, Pro $315/mo, Enterprise custom; 14-day trial | Active |
| **Google model-viewer** | Delegates to WebXR / Scene Viewer / Quick Look | Evergreen browsers for 3D; AR via platform handoff | Open source | Active |
| **three.js + WebXR** | Via WebXRManager (abstracts WebXR) | Anywhere WebXR works | MIT | Active |
| **Babylon.js + WebXR** | WebXR features incl. unbounded spaces, partial depth-sensing; body tracking planned | WebXR-capable; strong on Quest Browser | W3C Software & Document License (their note) | Active |
| **Needle Engine** | WebAR class with reticle + overlay, sample experiences | WebXR-capable | Not stated in evidence | Active, documented |
| **PlayCanvas** | WebXR AR + raycast + DOM overlay + hit test + image tracking + plane detection; Zappar integration | WebXR-capable | Free / $15/mo Personal / $50/seat Org | Active |
| **Wonderland Engine** | SLAM, marker, image, face, full-body (via Zappar/8th Wall/MindAR integrations) | WebXR + provider | Free under $120k/yr revenue; 10% royalty above | Active, 1.5.3 (2025) added Zappar templates |

---

## Per-project notes

### WebXR Device API (the platform)
- Spec: `https://www.w3.org/TR/webxr/`. AR module exposes optional features (`plane-detection`, image-tracking, etc.) that must be requested in session options and require device-native support.
- Quest Browser identified as the strongest passthrough-AR + depth WebXR implementation. visionOS 2+ ships WebXR more broadly; visionOS 1 required flags.
- WebGPU adoption is a watch item but is not yet a hard requirement for WebAR.

### AR.js
- Three flavors: marker (cheap, 60fps target), image/NFT (heavier CPU), location/GPS (compass-dependent — degraded on Firefox + many Androids).
- npm: `@ar-js-org/ar.js`. Docs: `https://ar-js-org.github.io/AR.js-Docs/`. Org also maintains `AR.js-next` and `LocAR.js`.
- Pure client-side — no cloud, good for privacy and low-cost hosting.

### A-Frame
- Declarative HTML scene API on top of three.js. AR comes from a provider you bolt in (AR.js, 8th Wall, Zappar, MindAR).
- 1.7.1 released April 2025; ES module support / import maps.

### MindAR
- Image and face tracking, both as pure JS libs. Open source MIT. Face mesh exposes 52 blendshapes — usable for AR filters / avatar puppeteering.
- Originally A-Frame-centric, now three.js-first since 1.1.0; ES modules since 1.2.5.
- Repo: `https://github.com/hiukim/mind-ar-js`.

### 8th Wall (Niantic Spatial)
- Was *the* commercial WebAR SLAM engine for years. Hosted Studio + Cloud + analytics + integrations for A-Frame/three.js/Babylon/PlayCanvas.
- **Hosted service retired 28 Feb 2026.** Engine, tools, and binaries now offered free / open. Published experiences keep running until 28 Feb 2027 per 8th Wall comms.
- Practical implication: anyone choosing 8th Wall today is choosing the now-open engine; existing customers need to migrate hosting elsewhere by 2027.

### Niantic Lightship VPS for Web
- Cloud visual positioning system — query image up, transform back. Cm-level accuracy at activated map sites globally.
- Integration path for the web is via 8th Wall.
- Compute- and bandwidth-intensive; requires Niantic API key / token flow. Sends imagery to Niantic — relevant privacy consideration.

### Zappar / ZapWorks Universal AR
- Multi-engine SDK (A-Frame, three.js, Babylon, PlayCanvas, Unity). Face + image + world tracking.
- Pricing tiers documented: Developer $12.99/mo or $64.99/yr, Pro $315/mo or $2,640/yr, Enterprise custom. 14-day trial.
- Also ships a no-code Designer and hosted projects.

### Google model-viewer
- Drop-in `<model-viewer>` web component for glTF/GLB. Handles:
  - 3D display in any modern browser (WebGL).
  - AR via WebXR where present.
  - Falls back to **Scene Viewer** (ARCore-backed native) on Android.
  - **Quick Look** (USDZ) on iOS via Apple's native viewer.
- Site: `https://modelviewer.dev/`. Best choice for product-viewer use cases where you don't need custom interaction logic.

### three.js + WebXR
- `WebXRManager` abstracts session lifecycle, base layer, depth-sensing feature checks. Most "hand-rolled" WebAR ends up here.
- Pair with `three-mesh-bvh`, `meshopt-decoder`, GLTFLoader for performance.

### Babylon.js + WebXR
- Built-in AR session support including unbounded reference space. Forum threads (2025) note: body tracking is on the roadmap, depth sensing is partially supported, multimodal input differs by device.
- Strong tooling/inspector; bigger learning curve than three.js but more batteries-included.

### Needle Engine
- Built on three.js + WebAssembly tooling, integrates with Unity for authoring. Has a documented `WebAR` class exposing reticle + DOM overlay.
- Pricing not documented in the evidence we collected — flag this for follow-up before adopting.

### PlayCanvas
- Browser-based editor + WebGL/WebGPU engine. WebXR AR features: raycast, DOM overlay, hit test, image tracking, plane detection. Marker AR via `playcanvas-ar` repo.
- Tiers: Free, Personal $15/mo, Organization $50/seat/mo. Privacy policy collects usage + location.

### Wonderland Engine
- WASM-backed engine + editor; integrates Zappar, 8th Wall, MindAR. Supports SLAM, marker, image, face, full-body.
- Free up to $120k/yr revenue, then 10% royalty (or enterprise license).
- 1.5.3 release added built-in Zappar AR templates.

---

## What the evidence didn't cover (gaps to chase)

- **Variant**, **Onirix**, **Awe.js**, **JSAR**, **Rocketbox** — requested in brief, no corroborating sources surfaced. Onirix and Awe.js are likely defunct/legacy; worth a direct site check.
- Concrete WebXR feature support per *exact* iOS Safari version in 2025–2026.
- Niantic Lightship VPS pricing tiers (commercial — likely sales-gated).
- Needle Engine licensing.
- Quantitative benchmarks (FPS, tracking jitter) across frameworks.

---

## References

1. WebXR plane detection — https://immersive-web.github.io/plane-detection/
2. W3C WebXR spec — https://www.w3.org/TR/webxr/
3. Zappar — WebXR on Vision Pro deep dive — https://www.zappar.com/insights/how-to-create-webxr-experiences-on-vision-pro-a-technical-deep-dive
4. MDN WebXR Device API — https://developer.mozilla.org/en-US/docs/Web/API/WebXR_Device_API
5. BrowserStack WebXR compatibility — https://www.browserstack.com/guide/webxr-and-compatible-browsers
6. three.js WebXRManager — https://threejs.org/docs/pages/WebXRManager.html
7. Babylon forum — WebXR features — https://forum.babylonjs.com/t/support-for-latest-webxr-features-in-babylon-js/54642
8. AR.js docs — https://ar-js-org.github.io/AR.js-Docs/
9. AR.js GitHub — https://github.com/AR-js-org/AR.js/
10. Zappar Universal AR (A-Frame) — https://zap.works/universal-ar/aframe/
11. A-Frame docs — https://aframe.io/docs/
12. MindAR releases — https://github.com/hiukim/mind-ar-js/releases
13. MindAR docs — https://hiukim.github.io/mind-ar-js-doc/
14. Google Scene Viewer — https://developers.google.com/ar/develop/scene-viewer
15. model-viewer — https://modelviewer.dev/
16. model-viewer + WebXR — https://developers.google.com/ar/develop/webxr/model-viewer
17. Zappar pricing — https://zap.works/pricing/
18. 8th Wall docs (legacy) — https://8thwall.com/docs/legacy/guides/advanced-topics/device-authorization/
19. 8th Wall (post-retirement) — https://8thwall.org/
20. 8th Wall pricing forum — https://forum.8thwall.com/t/price-tiers-discrepancy-in-documentation/7603
21. Niantic Lightship VPS for Web — https://nianticlabs.com/news/lightship-vps-web/
22. Niantic VPS architecture — https://nianticlabs.com/news/vps-part-3/
23. Niantic Spatial SDK release notes — https://nianticspatial.com/docs/nsdk/release_notes/index.html
24. Needle Engine samples — https://engine.needle.tools/samples/
25. Needle Engine WebAR API — https://engine.needle.tools/docs/api/@needle-tools/engine/3.16.2/classes/engine_components_api.WebAR.html
26. PlayCanvas AR tag — https://developer.playcanvas.com/tags/ar/
27. PlayCanvas-AR repo — https://github.com/playcanvas/playcanvas-ar
28. PlayCanvas plans — https://playcanvas.com/plans
29. Wonderland docs — https://wonderlandengine.com/documentation/
30. Wonderland AR quick-start — https://wonderlandengine.com/getting-started/quick-start-ar/
31. Wonderland release 1.5.3 — https://wonderlandengine.com/news/release-1.5.3/
32. Wonderland pricing — https://wonderlandengine.com/pricing/
