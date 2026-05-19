# AR Methodologies & CV Techniques (2024–2026)

**Source:** Tavily `pro` research, 2026-05-18.

---

## TL;DR — What technique for what job?

| Job | Use |
|---|---|
| **Mobile world tracking** | VIO (visual-inertial SLAM). ARKit + ARCore both do this; tight-coupling gives metric scale + drift resilience |
| **Persistent low-latency placement (constrained env)** | Fiducial markers (ArUco, QR, AprilTag) — <3 ms latency possible with event sensors |
| **Brand/product anchored to a known image** | Natural Feature Tracking (NFT) / image tracking — Vuforia, AR.js, 8th Wall, AR Foundation |
| **Place virtual objects on floors/walls** | Plane detection (horizontal, vertical, **slanted** since ARKit WWDC '24) |
| **Realistic occlusion** | Active depth (LiDAR/ToF) where available; otherwise monocular depth + segmentation fusion |
| **Face filters / avatars** | ARKit face anchor (50+ blendshapes, 60Hz) on TrueDepth; MediaPipe FaceMesh (468 landmarks) cross-platform |
| **Hand interaction** | MediaPipe Hands (21 landmarks/hand), or platform hand tracking (Quest, Vision Pro) |
| **Person occlusion** | MediaPipe Selfie Segmentation (~2m); ARKit People Occlusion (LiDAR) |
| **Centimeter-level outdoor positioning** | VPS — Niantic Lightship, Immersal, ARCore Geospatial |
| **High-fidelity scene capture for AR** | Gaussian Splatting (gsplat, Mobile-GS) — mobile feasibility improving fast |

---

## 1. SLAM: visual-inertial (VIO) vs visual-only

- **Visual-only SLAM**: cameras only. **Cannot recover metric scale.** Sensitive to lighting, rolling shutter, fast motion. Direct methods (DSO, LSD) have higher error than feature-based on mobile data.
- **VIO/VI-SLAM**: fuses IMU + camera. Recovers metric scale, robust to rapid motion.
  - Filter-based (EKF/MSCKF) vs optimization-based (sliding window).
  - Loose-coupled vs **tightly-coupled** (preferred for scale recovery).
- **Reference systems**: OKVIS, VINS-Mono, OpenVINS, ORB-SLAM3 (supports VI mode).
- **ARKit & ARCore both use VIO.** ARKit samples IMU at ~1000 Hz.

**Failure modes**: low texture, fast motion, drastic lighting change, reflective surfaces, dynamic scenes. Mitigations: learned descriptors (SuperPoint/SuperGlue), GPU offload, hardware-software co-design (optical flow on DSP).

## 2. Marker-based tracking

- **ArUco**, **AprilTag**, **QR** — engineered planar fiducials. Reliable, cheap, fast.
- Event-camera variants reach <3 ms latency.
- **Weaknesses**: physical marker required, specular reflection, partial occlusion, planar pose ambiguity from noisy corners.
- **SDKs**: AR Foundation (markers including QR/ArUco/AprilTag), OpenCV ArUco, AR.js, Vuforia. Example combining ArUco + ARKit persistence: `natwales/aruco-arkit-localizer`.

## 3. Natural Feature Tracking (NFT) / image tracking

- Match stored target image features to live frames → create image anchor.
- Works best on **rich, high-contrast, non-repetitive** textures. Degrades with gloss/reflection/repetition.
- Vuforia rates image quality with a star system; pick targets accordingly.
- SDKs: Vuforia Image Targets / Model Targets, AR Foundation, AR.js, 8th Wall, MindAR.
- **Optimization**: disable world SLAM when only image-anchored content is needed.

## 4. Plane detection — horizontal, vertical, slanted

- Slab-fits 3D structure from VIO + optional depth.
- ARKit (WWDC '24) introduced **slanted plane alignment** in addition to horizontal/vertical.
- ARCore session config controls which plane types are detected (turn off unused types to save power).
- AR Foundation plane subsumption API merges newly detected with existing planes.

## 5. Depth: monocular (learning) vs LiDAR vs ToF vs Structured Light

| Source | Strengths | Weaknesses | Where |
|---|---|---|---|
| **Monocular depth (ML)** | No extra HW; flexible | Scale ambiguity; variable accuracy | Depth Anything V2, MiDaS/DPT, ZoeDepth |
| **LiDAR** | Metric, long-range | Cost, indoor/outdoor tradeoffs, power | iPhone Pro line, Vision Pro, iPad Pro |
| **ToF** | Low latency, low power | Poor outdoors; range/noise tradeoff | Some Android devices |
| **Structured Light** | High precision close-range | Noise grows quadratically with distance | TrueDepth (front-cam) |
| **Stereo IR pattern** | Mid-range depth, headset-friendly | Power cost | Quest 3 (IR emitter + 2 IR cameras) |

**Fusion** is the modern winner: sparse LiDAR as a prompt/constraint for monocular ML depth decoders (FusionDepth and similar) significantly outperforms pure monocular.

## 6. Occlusion

### Environment occlusion (geometry/depth)
- **ARKit Scene Geometry** + **Quest 3 Mesh API / Depth API**: reconstructed meshes / depth frames for compositing.
- KinectFusion-style dense reconstructions remain the conceptual basis.
- Quest 3 Depth API noted as CPU/GPU/battery heavy and experimental.
- Reflective surfaces and large monitors break depth.

### People occlusion (segmentation)
- **MediaPipe Selfie Segmentation** — real-time, ~2m range, mobile-friendly.
- **ARKit People Occlusion** — uses LiDAR for per-pixel depth on Pro devices.
- Semantic SLAM variants (Mask-SLAM, DS-SLAM, Dynamic-VINS) handle moving objects but are heavier than baseline VIO.

## 7. Light estimation

- ARKit + ARCore both return ambient intensity, color correction, main light direction, **spherical harmonics** on supported devices.
- ARKit face capture can supply spherical-harmonic environment from the face data.
- Engines surface this as directional light + ambient SH coefficients (PlayCanvas, three.js).

## 8. Face tracking

- **MediaPipe Face Mesh**: **468 3D landmarks**, single-camera, GPU-accelerated, runs in real time on mobile. (478 variant adds iris landmarks.)
- **ARKit ARFaceAnchor**: 3D topology + 50+ blendshapes, 60 Hz, requires TrueDepth for highest fidelity (front-cam ML-only on non-TrueDepth devices).

## 9. Hand & body tracking

- **MediaPipe Hands**: 21 3D landmarks/hand, multi-hand.
- **MediaPipe Holistic**: face + hand + body pose in one pipeline, on-device.
- Quest / Vision Pro expose system-level hand tracking (no details in evidence corpus).

## 10. Anchors — image, object, persistent, cloud

- All major SDKs support 6DoF anchors from hit-tests, image targets, or detected objects (Vuforia Anchor Target Observer).
- **Local persistence**: serialize anchor + reference data on device (aruco-arkit-localizer pattern).
- **Cloud anchors**: ARCore Cloud Anchors / Persistent Cloud Anchors. ARKit also documents cross-device anchor support. Subject to quotas + privacy considerations.

## 11. Visual Positioning Systems (VPS)

- **Niantic Lightship VPS**: centimeter-class pose in seconds at VPS-activated locations. User-submitted scans build the map.
- **Immersal**: similar, stadium-scale, advertises cm-class accuracy.
- **ARCore Geospatial VPS**: covered in the native-mobile findings; relies on Google Street View VPS.
- **Requirements**: prebuilt maps from scans; mapping is time- and data-intensive.

## 12. Mesh reconstruction & depth-aware compositing

- Real-time meshes from sensor depth → occlusion + collision.
- Quest 3 Scene Mesh + Mesh API. ARKit Scene Geometry.
- Real-time meshing on consumer hardware costs significant CPU/GPU/battery; budget accordingly.

## 13. Semantic scene segmentation

- Improves plane detection, dynamic-object rejection, placement restriction.
- Lightweight backbones (MobileNetV3 + Lite R-ASPP, ContextFormer) hit acceptable mIoU at mobile-friendly GFLOPs.
- Niantic Lightship's cross-platform semantic segmentation is the most production-ready mobile offering on non-LiDAR devices.

## 14. Neural rendering — NeRF & 3D Gaussian Splatting

- **3D Gaussian Splatting (3DGS / gsplat)**: faster render + lower memory than NeRF for novel-view synthesis. Training still GPU-heavy.
- **Mobile-GS**: high FPS on Snapdragon-class GPUs with compact storage — mobile rendering is now feasible.
- Production capture tools (in tech-stack note): Luma AI, Polycam, Scaniverse, KIRI Engine, gsplat.js / splatviz for web.
- **Integration into live AR**: still a hard problem at the runtime level — typically used for capture/asset creation rather than real-time alignment with VIO, but the trajectory is clear.

## 15. Passthrough AR (Quest 3, Vision Pro) vs phone AR

| Aspect | Headset passthrough | Phone AR |
|---|---|---|
| **Depth** | Dense, low-latency from onboard sensors (IR stereo / LiDAR) | LiDAR on Pro phones; otherwise ML monocular |
| **Occlusion** | Mesh + Depth APIs immediate | LiDAR if present; otherwise composited from ML depth |
| **Hand tracking** | System-level | Camera-only ML (less reliable) |
| **Power** | Headset constrained, but on-device GPU is more capable | Phone budget tighter |
| **Reach** | Single user, niche hardware | Billions of phones |

Quest 3 Depth API range: coarse depth to ~4–5m with decaying accuracy.

## 16. Learned features + descriptor matching

- **SuperPoint + SuperGlue**: ~70 ms per 512-keypoint pair on standard GPU.
- Replacing classical ORB in modern relocalization / multi-session mapping pipelines.
- GPU offload makes this viable on mobile.

---

## Decision checklist (cheat-sheet)

1. **Indoor, single-session, simple placement** → Plane detection + VIO. Phone AR via ARKit/ARCore + AR Foundation.
2. **Persistent across sessions, single device** → Local anchor serialization.
3. **Persistent across users/devices, indoor** → Niantic VPS or Immersal (map the space first).
4. **City scale outdoor** → ARCore Geospatial.
5. **Realistic occlusion** → LiDAR if available, otherwise plan an ML depth+segmentation fallback.
6. **High-fidelity asset capture** → Object Capture (Apple) or Polycam/Luma (Gaussian Splatting).
7. **Browser-only delivery** → AR.js for markers, MindAR for image/face, model-viewer for product viewers, three.js+WebXR for custom.

---

## Evidence gaps

- ARCore Geospatial internal technical details (covered separately in mobile findings).
- NeRF foundation papers + Luma/Polycam vendor integration details not in this corpus.
- Privacy/legal/regulatory specifics per platform.
- Quantitative latency benchmarks across ARKit/ARCore hardware generations.

---

## References

1. VI-SLAM benchmark — https://cad.zju.edu.cn/home/gfzhang/projects/vrih-vislam-benchmark.pdf
2. SLAM survey — https://arxiv.org/html/2310.15072v3
3. OKVIS project — https://projects.asl.ethz.ch/okvis/
4. VINS-Mono — https://cad.zju.edu.cn/home/gfzhang/dataset/ISMAR2019-SLAM-Challenge/ismar-system-description/VINS-Mono.pdf
5. OpenVINS — https://github.com/robintzeng/EECS568_team_14_open_vins
6. ARKit docs — https://developer.apple.com/documentation/arkit
7. ARCore fundamentals — https://developers.google.com/ar/develop/fundamentals
8. ARCore runtime — https://developers.google.com/ar/develop/runtime
9. ORB-SLAM3 — https://ar5iv.labs.arxiv.org/html/2007.11898
10. SuperPoint/SuperGlue overview — https://arxiv.org/html/2506.13089v2
11. aruco-arkit-localizer — https://github.com/natwales/aruco-arkit-localizer
12. AR Foundation markers — https://docs.unity3d.com/Packages/com.unity.xr.arfoundation@6.4/manual/features/markers/introduction.html
13. ArUco OpenCV tutorial — https://learnopencv.com/augmented-reality-using-aruco-markers-in-opencv-c-python/
14. AR.js image tracking — https://ar-js-org.github.io/AR.js-Docs/image-tracking/
15. Vuforia model targets — https://developer.vuforia.com/library/vuforia-engine/images-and-objects/model-targets/optimizing-model-target-tracking/
16. Event-based fiducial tracking — https://publications.ait.ac.at/en/publications/event-based-high-speed-low-latency-fiducial-marker-tracking
17. WebAR.rocks object — https://github.com/WebAR-rocks/WebAR.rocks.object
18. 8th Wall studio image targets — https://github.com/8thwall/studio-image-targets-example
19. Vuforia ground plane — https://developer.vuforia.com/library/vuforia-engine/environments/ground-plane/ground-plane/
20. ARKit WWDC23 plane talk — https://developer.apple.com/videos/play/wwdc2023/10100/
21. Depth Anything — https://depth-anything.github.io/
22. Depth Anything V2 article — https://digitalocean.com/community/tutorials/depth-anything-v2-a-powerful-monocular-depth-estimation-model
23. Monocular depth overview — https://ultralytics.com/blog/what-is-monocular-depth-estimation-an-overview
24. ToF sensor knowledge — https://tofsensors.com/blogs/tof-sensor-knowledge/tof-camera-light-lidar-3d-imaging
25. Structured light depth noise — https://openaccess.thecvf.com/content_ICCV_2017_workshops/papers/w34/usage_bh711.parksamsung.com_y.c.kehsamsung.com_ofldhsamsung.com_ICCV_2017_paper.pdf
26. KinectFusion follow-up — https://marciocerqueira.github.io/docs/publications/2021-TVCG.pdf
27. Occlusion in AR (Milvus quick reference) — https://milvus.io/ai-quick-reference/what-is-occlusion-in-ar-and-how-is-it-managed
28. MediaPipe Selfie Segmentation — https://chuoling.github.io/mediapipe/solutions/selfie_segmentation.html
29. Quest 3 scene meshing — https://uploadvr.com/developer-implemented-continuous-scene-meshing-quest-3-lasertag/
30. Meta Mesh + Depth API blog — https://developers.meta.com/horizon/blog/mesh-depth-api-meta-quest-3-developers-mixed-reality/
31. Light estimation in Unity — https://tutorialsforar.com/using-light-estimation-in-ar-using-arkit-and-arcore-with-unity/
32. PlayCanvas WebXR light estimation — https://developer.playcanvas.com/user-manual/xr/ar/light-estimation/
33. ARKit face tracking docs — https://developer.apple.com/documentation/arkit/tracking-and-visualizing-faces
34. MediaPipe FaceMesh — https://mediapipe.readthedocs.io/en/latest/solutions/face_mesh.html
35. MediaPipe Holistic (Google blog) — https://research.google/blog/mediapipe-holistic-simultaneous-face-hand-and-pose-prediction-on-device/
36. MediaPipe Hands — https://mediapipe.readthedocs.io/en/latest/solutions/hands.html
37. Quest 3 wiki — https://en.wikipedia.org/wiki/Meta_Quest_3
38. FusionDepth — https://github.com/AutoAILab/FusionDepth
39. Niantic VPS docs — https://nianticspatial.com/docs/nsdk/features/lightship_vps/
40. Immersal stadium AR PDF — https://immersal.com/hubfs/PDFs/Spatial%20Computing%20and%20AR%20Stadium%20Apps%20Redefining%20Fan%20Experiences%20-article%20-Immersal.pdf
41. ContextFormer segmentation — https://arxiv.org/html/2501.19255v1
42. DeepLabV3+ MobileNet — https://aihub.qualcomm.com/models/deeplabv3_plus_mobilenet
43. gsplat evaluation — https://docs.gsplat.studio/main/tests/eval.html
44. Mobile-GS project — https://xiaobiaodu.github.io/mobile-gs-project/
45. SuperGlue topic — https://emergentmind.com/topics/superglue
