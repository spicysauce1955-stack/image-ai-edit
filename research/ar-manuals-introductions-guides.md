# AR Manuals, Introductions, and Guides - Research Log
**Research Date:** 2026-05-18

---

## Research Process

### Search Strategy
1. Examined official documentation sites for ARCore (Google), ARKit (Apple), AR Foundation (Unity), SceneView, AR.js, and WebXR
2. Explored GitHub repos for sample code, README docs, and quickstart guides
3. Reviewed Google's AR design guidelines
4. Looked at open-source project documentation (SceneView, AR Foundation samples, ARCore SDK)
5. Searched for curated learning resource lists (Awesome-ARKit, Awesome-ARCore)

---

## 1. Official Platform Documentation

### 1.1 Google ARCore Documentation
- **URL:** https://developers.google.com/ar/develop
- **Quality:** Excellent - comprehensive, well-organized, multi-platform
- **Key Sections:**
  - **Fundamentals:** Motion tracking, environmental understanding, depth, light estimation, hit-testing, anchors & trackables, augmented images
  - **Getting Started:** Quickstarts for Android (Kotlin/Java), Android NDK (C), Unity (AR Foundation), iOS, Unreal, and WebXR
  - **Feature Guides (per platform):**
    - Camera configuration & metadata
    - Hit-test (raycasting from screen to world)
    - Recording & Playback (record AR sessions, replay later)
    - Instant Placement (place objects before full tracking is ready)
    - Depth API (occlusion, depth maps)
    - Lighting Estimation (match virtual object lighting to real world)
    - Augmented Faces & Images
    - Cloud Anchors (shared AR experiences across devices)
    - Geospatial API (GPS-anchored AR, Streetscape Geometry, VPS)
    - Scene Semantics (ML-based scene understanding: sky, ground, buildings)
    - Electronic Image Stabilization
    - Machine Learning with ARCore
    - Vulkan Rendering
  - **UX Design Guidelines:** https://developers.google.com/ar/design
    - Environment definition, experience size, movement, safety & comfort, realism, content placement, content manipulation, interaction UX, UI elements
  - **Debugging:** Call logging, performance overlay
  - **Publishing:** Runtime considerations, performance considerations, privacy requirements, Play Store publishing

**Relevance to Yard Object AR:** HIGH - The fundamental guides on plane detection, hit-testing, anchors, instant placement, and scene semantics are directly applicable. The Geospatial API enables persistent outdoor placement.

### 1.2 Apple ARKit Documentation
- **URL:** https://developer.apple.com/documentation/arkit/
- **URL:** https://developer.apple.com/augmented-reality/
- **Quality:** Excellent - Apple's official docs are comprehensive
- **Key Components:**
  - **ARKit** - Core AR framework for iOS/iPadOS
  - **RealityKit** - High-level 3D/AR framework with object placement, rendering
  - **RoomPlan** - Room scanning API (creates 3D models of rooms)
  - **AR Creation Tools** - Reality Composer, Reality Composer Pro
  - **AR Quick Look** - Preview USDZ models in AR
  - **Object Capture** - Photogrammetry API to create 3D models from photos
- **Key ARKit Features:**
  - World tracking (6DOF)
  - Plane detection (horizontal, vertical)
  - Image tracking
  - Object scanning & detection
  - Body/face/hand tracking
  - People occlusion
  - Scene geometry (LiDAR - creates mesh of environment)
  - Raycasting (hit testing)
  - Collaborative sessions (shared AR)

**Relevance to Yard Object AR:** MEDIUM-HIGH - ARKit is essential for iOS. Scene geometry with LiDAR iPad/iPhone creates outdoor meshes. Plane detection works for ground surfaces. Object Capture can create 3D yard object models from photos.

### 1.3 Unity AR Foundation Documentation
- **URL:** https://docs.unity3d.com/Packages/com.unity.xr.arfoundation@6.4/manual/index.html
- **GitHub Samples:** https://github.com/Unity-Technologies/arfoundation-samples (3.4k stars)
- **Unity Manual AR Section:** https://docs.unity3d.com/Manual/AROverview.html
- **Quality:** Excellent - cross-platform AR SDK documentation
- **Key Concepts:**
  - AR Session + XR Origin as required scene elements
  - AR Manager components for each feature (plane detection, image tracking, etc.)
  - AR provider plug-ins: Apple ARKit, Google ARCore, OpenXR
  - XR Interaction Toolkit for AR gestures (drag, scale, rotate, place)
  - AR Mobile template for rapid project setup
- **Samples Include:**
  - Plane detection, image tracking, face tracking
  - Object placement (directly relevant for yard objects)
  - AR annotations
  - Checkpoints, environment probes, human body tracking
- **Unity 6.4 compatibility:** AR Foundation 6.4+
- **Platform Support:** iOS, Android, visionOS, Meta Quest, Android XR

**Relevance to Yard Object AR:** HIGH - Unity AR Foundation is the most popular cross-platform AR game engine approach. The XR Interaction Toolkit's AR placement interactable is designed exactly for tap-to-place object UX.

### 1.4 SceneView Documentation
- **URL:** https://sceneview.github.io/docs/
- **GitHub:** https://github.com/sceneview/sceneview (1.2k stars)
- **Quality:** Very Good - comprehensive README + AI-friendly llms.txt
- **Key Concepts:**
  - **Android:** Filament engine + Jetpack Compose (declarative) - only Compose-native 3D library
  - **iOS:** RealityKit + SwiftUI
  - **Web:** Filament.js WASM + sceneview.js (~25KB DSL)
  - **Cross-platform:** KMP shared core (math, collision, geometry, physics)
  - **35+ Node Types:** ModelNode, CubeNode, SphereNode, AnchorNode, HitResultNode, etc.
  - **AR Features:** Full ARCore surface; plane rendering, hit-test, anchors, Geospatial, Cloud Anchors, Augmented Images/Faces
  - **AR-Specific Nodes:** AnchorNode, HitResultNode, PoseNode, CloudAnchorNode, StreetscapeGeometryNode, TerrainAnchorNode, RooftopAnchorNode
  - **Special:**
    - Record & Replay AR sessions (debug without phone)
    - Rerun.io live debug visualization
    - MCP server (28 tools, 33 samples) for AI-assisted development
    - `isEditable` flag for gesture-driven object manipulation
- **Code Example (AR - Android/Kotlin):**
  ```kotlin
  var anchor by remember { mutableStateOf<Anchor?>(null) }
  ARSceneView(
      modifier = Modifier.fillMaxSize(),
      planeRenderer = true,
      onSessionUpdated = { _, frame ->
          if (anchor == null) {
              anchor = frame.getUpdatedPlanes()
                  .firstOrNull { it.type == Plane.Type.HORIZONTAL_UPWARD_FACING }
                  ?.let { frame.createAnchorOrNull(it.centerPose) }
          }
      }
  ) {
      anchor?.let {
          AnchorNode(anchor = it) {
              ModelNode(modelInstance = model, scaleToUnits = 0.5f)
          }
      }
  }
  ```
- **Code Example (AR - iOS/Swift):**
  ```swift
  ARSceneView(planeDetection: .horizontal) { position, arView in
      GeometryNode.cube(size: 0.1, color: .blue)
          .position(position)
  }
  ```

**Relevance to Yard Object AR:** VERY HIGH - SceneView provides the exact primitives needed: detect horizontal plane → create anchor → place 3D model node. The `isEditable` flag enables drag/rotate/scale. Terrain/Rooftop anchors enable GPS-based yard placement.

---

## 2. Web-Based AR Documentation

### 2.1 WebXR Documentation
- **W3C Spec:** https://github.com/immersive-web/webxr (3.1k stars)
- **MDN Docs:** https://developer.mozilla.org/en-US/docs/Web/API/WebXR_Device_API
- **Google ARCore WebXR:** https://developers.google.com/ar/develop/webxr
- **Key Pages:**
  - WebXR requirements
  - Hello WebXR sample
  - AR with `<model-viewer>` component
  - Hit-test explainer
- **AR.js (5.9k stars):** https://github.com/AR-js-org/AR.js
  - Image tracking, location-based AR, marker tracking
  - Works with A-Frame for declarative WebXR
  - Lightweight, runs in browser
- **MindAR.js (2.7k stars):** https://github.com/hiukim/mind-ar-js
  - Web AR with image tracking, face tracking
  - Tensorflow.js integration
- **Google Model Viewer (8.1k stars):** https://github.com/google/model-viewer
  - Web component for 3D model display with AR Quick Look
  - One `<model-viewer>` tag to display glTF/GLB with "View in AR" button
  - AR integration for both iOS (AR Quick Look) and Android (Scene Viewer)

**Relevance to Yard Object AR:** MEDIUM - Web-based AR is simpler but less capable than native for outdoor placement. `<model-viewer>` is best for simple "preview this 3D model in your space" experiences. AR.js location-based AR could work for GPS-anchored yard layouts.

---

## 3. Curated Resource Lists

### 3.1 Awesome-ARKit (8k stars)
- **URL:** https://github.com/olucurious/Awesome-ARKit
- **Content:** Curated list of ARKit projects, tutorials, libraries, and tools
- **Categories:** Getting started, tutorials, libraries/frameworks, sample code, experiments, design guidelines, blogs, books, podcasts

### 3.2 Awesome-ARCore (134 stars)
- **URL:** https://github.com/olucurious/Awesome-ARCore
- **Content:** Curated ARCore resources (less comprehensive than ARKit list)

### 3.3 Google AR Codelabs
- **URL:** https://codelabs.developers.google.com/?category=ar
- **Content:** Hands-on step-by-step tutorials for ARCore:
  - Cloud Anchors codelab
  - Geospatial API codelab
  - Scene Semantics + Geospatial Depth codelab
  - Streetscape Geometry + Rooftop Anchors codelab

---

## 4. Key Design Guides

### 4.1 Google AR Design Guidelines
- **URL:** https://developers.google.com/ar/design
- **Sub-pages:**
  - Environment: Definition, experience size
  - User: Movement, safety & comfort
  - Content: Realism, content placement, content manipulation
  - Interaction: UX patterns, UI elements
- **Key Principles:**
  - AR objects should respect real-world scale
  - Use familiar gestures (tap, drag, pinch)
  - Provide clear affordances for object placement
  - Consider environment lighting for realistic rendering
  - Plan for physical safety (users walking while looking at phone)
  - Keep UI minimal; let the real world be the interface

### 4.2 Apple AR Human Interface Guidelines
- **URL:** https://developer.apple.com/design/human-interface-guidelines/augmented-reality
- **Key Points:**
  - Place objects at comfortable viewing distance
  - Use realistic lighting and shadows
  - Provide feedback when surfaces are detected
  - Support direct manipulation (drag, rotate, scale)
  - Consider ergonomics (avoid requiring users to hold device at awkward angles)
  - Gracefully handle tracking loss

---

## 5. Open-Source Code Samples & Starter Projects

### 5.1 AR Foundation Samples (Unity)
- **Repo:** https://github.com/Unity-Technologies/arfoundation-samples (3.4k stars)
- **What it includes:** 30+ sample scenes covering every AR Foundation feature
- **Relevant samples:**
  - Plane detection & placement
  - AR placement interactable (XR Interaction Toolkit)
  - AR annotations
  - Camera image tracking
  - Checkpoints (persistent anchors)
  - Environment probes (lighting)

### 5.2 SceneView Samples (Android/iOS/Web/Flutter/React Native)
- **Repo:** https://github.com/sceneview/sceneview/tree/main/samples
- **Samples:** android-demo, ios-demo, web-demo, desktop-demo, flutter-demo, react-native-demo
- **Relevant capabilities:**
  - AR plane detection + model placement
  - AR recording & playback
  - AR Rerun.io debug
  - Gesture-driven manipulation (isEditable)
  - Geospatial anchors

### 5.3 Google ARCore Samples
- **Android SDK:** https://github.com/google-ar/arcore-android-sdk (5.2k stars)
  - hello_ar_java, hello_ar_c, shooting_stars, raw_depth, augmented_image, cloud_anchor, etc.
- **Depth Lab:** https://github.com/googlesamples/arcore-depth-lab (862 stars)
  - Depth API samples for occlusion, interaction, rendering
- **AR Drawing:** https://github.com/googlecreativelab/ar-drawing-java (412 stars)
  - Simple AR drawing app demonstrating ARCore usage

### 5.4 CamAR (ARKit minimal example)
- **Repo:** https://github.com/hooverti/CamAR (3 stars)
- **What it does:** Minimal ARKit app showing plane detection + object placement
- **Good for:** Understanding the core interaction loop for yard object placement

### 5.5 ARKit-CoreLocation (5.5k stars)
- **Repo:** https://github.com/AndrewHartAR/ARKit-CoreLocation
- **What it does:** Combines AR accuracy with GPS scale for outdoor AR
- **Good for:** GPS-anchored outdoor experiences (placing objects at real coordinates)

---

## 6. Learning Path for Building "Yard Object AR" Feature

### Phase 1: Fundamentals (1-2 weeks)
1. **ARCore Fundamentals:** https://developers.google.com/ar/develop/fundamentals
   - Motion tracking, environmental understanding, depth, light estimation
   - Hit-testing, anchors, augmented images
2. **ARKit Fundamentals:** https://developer.apple.com/documentation/arkit
   - World tracking, plane detection, raycasting
3. **Google AR Design Guidelines:** https://developers.google.com/ar/design
   - Content placement, realistic rendering, user comfort

### Phase 2: Platform-Specific Deep Dive (2-3 weeks)
Choose one or more of:

**Option A: Native Android (Kotlin + SceneView)**
1. SceneView README: https://github.com/sceneview/sceneview
2. SceneView AR docs: AR Scene section of README
3. ARSceneView + plane detection + AnchorNode pattern
4. SceneView samples (android-demo)
5. ARCore documentation: Plane detection, hit-test, depth, Geospatial

**Option B: Native iOS (Swift + ARKit/SceneView)**
1. SceneViewSwift section of SceneView repo
2. ARKit documentation + Apple AR HIG
3. SceneKit/ARKit plane detection + ARAnchor pattern
4. ARKit-CoreLocation for GPS anchoring

**Option C: Unity (C# + AR Foundation)**
1. Unity AR Foundation docs: https://docs.unity3d.com/Packages/com.unity.xr.arfoundation@6.4/
2. AR Foundation samples: https://github.com/Unity-Technologies/arfoundation-samples
3. XR Interaction Toolkit AR placement
4. ARCore Extensions for Unity (Geospatial, Cloud Anchors)

**Option D: Web (Three.js + WebXR / AR.js + A-Frame)**
1. WebXR specification: https://github.com/immersive-web/webxr
2. Google WebXR guide: https://developers.google.com/ar/develop/webxr
3. `<model-viewer>` for simple AR previews
4. AR.js for location-based outdoor AR

### Phase 3: Yard-Object Specific Implementation (3-6 weeks)
1. Implement plane detection (horizontal for ground/patio)
2. Implement hit-test → anchor creation → 3D model placement
3. Add object manipulation (drag, rotate, scale)
4. Create or source 3D models (glTF/GLB for Android/Web, USDZ for iOS)
5. Implement persistence (Cloud Anchors or Geospatial API)
6. Add measurement functionality (distance between placed objects)
7. Handle outdoor-specific challenges (lighting, tracking drift, scale)

---

## 7. Key Technical Concepts Glossary

| Concept | Description | Yard Object Relevance |
|---------|-------------|----------------------|
| **Plane Detection** | Detecting horizontal/vertical surfaces | Detect lawn, patio, driveway ground planes |
| **Hit-Test** | Raycast from screen to world to find position | Tap-to-place fences, pools on detected surfaces |
| **Anchor** | Fixed position in world space that AR tracks over time | Pin placed yard objects so they stay in position |
| **Trackable** | AR-tracked object (plane, point, image) | Ground plane trackable = detected yard surfaces |
| **Depth** | Distance from camera to surfaces | Occlusion: fence behind tree, pool edge in front of grass |
| **Light Estimation** | Environmental lighting data | Realistic shadows and reflections on placed objects |
| **Geospatial API** | GPS + VPS anchored content | Place objects at exact yard coordinates |
| **Scene Semantics** | ML scene understanding labels | Distinguish lawn, patio, sky, building |
| **Cloud Anchors** | Persistent anchors across sessions/devices | Share yard design with contractor |
| **Instant Placement** | Place before full tracking established | Immediate visual feedback when user taps |
| **glTF/GLB** | 3D model format (Web/Android standard) | Fence, pool, pergola models |
| **USDZ** | 3D model format (Apple standard) | Same models on iOS |

---

## 8. Essential URLs Quick Reference

| Resource | URL |
|----------|-----|
| ARCore Docs | https://developers.google.com/ar/develop |
| ARCore Fundamentals | https://developers.google.com/ar/develop/fundamentals |
| ARCore Design Guidelines | https://developers.google.com/ar/design |
| ARCore Codelabs | https://codelabs.developers.google.com/?category=ar |
| ARKit Docs | https://developer.apple.com/documentation/arkit |
| Apple AR Overview | https://developer.apple.com/augmented-reality/ |
| ARKit HIG | https://developer.apple.com/design/human-interface-guidelines/augmented-reality |
| Unity AR Foundation | https://docs.unity3d.com/Packages/com.unity.xr.arfoundation@6.4/ |
| Unity AR Overview | https://docs.unity3d.com/Manual/AROverview.html |
| AR Foundation Samples | https://github.com/Unity-Technologies/arfoundation-samples |
| SceneView (Android/iOS/Web) | https://github.com/sceneview/sceneview |
| SceneView Docs | https://sceneview.github.io/docs/ |
| SceneView Playground | https://sceneview.github.io/playground.html |
| AR.js | https://github.com/AR-js-org/AR.js |
| Model Viewer | https://github.com/google/model-viewer |
| WebXR Spec | https://github.com/immersive-web/webxr |
| WebXR MDN | https://developer.mozilla.org/en-US/docs/Web/API/WebXR_Device_API |
| A-Frame | https://github.com/aframevr/aframe |
| ARKit-CoreLocation | https://github.com/AndrewHartAR/ARKit-CoreLocation |
| ARCore Android SDK | https://github.com/google-ar/arcore-android-sdk |
| ARCore Depth Lab | https://github.com/googlesamples/arcore-depth-lab |
| Awesome-ARKit | https://github.com/olucurious/Awesome-ARKit |
| Awesome-ARCore | https://github.com/olucurious/Awesome-ARCore |