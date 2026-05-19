# Open-Source AR Projects for Physical Object Placement in the Real World
## Focus: Yard Objects (Fences, Pools, Landscaping, etc.)

**Research Date:** 2026-05-18

---

## Research Process

### Search Strategy
1. Searched GitHub for AR projects matching topics: "AR yard objects," "AR landscape visualization," "AR home improvement," "AR fence pool placement," "AR garden design," "ARKit plane detection object placement," "ARCore ARKit place objects real world"
2. Browsed GitHub topics for `augmented-reality` and `arcore`
3. Reviewed Google ARCore official developer documentation and SDKs
4. Examined Google's official `google-ar` organization repositories
5. Searched for specific repos: CamAR, SceneView, AR.js, model-viewer, etc.

### Key Finding
**No dedicated open-source project exists specifically for placing yard objects (fences, pools, etc.) in AR.** This is a niche that appears to be commercially served (by apps like IKEA Place, Houzz, etc.) but lacks a focused open-source solution. However, there are several **foundational frameworks and building blocks** that can be composed to build such a system.

---

## Foundational AR Frameworks & SDKs

### 1. Google ARCore (Android/Native)
- **Repo:** https://github.com/google-ar/arcore-android-sdk (5.2k stars)
- **Language:** C++/Java/Kotlin
- **Key Features:**
  - **Plane Detection** - Detects horizontal and vertical surfaces (ground, walls, tables) - essential for placing yard objects on ground plane
  - **Depth API** - Measures distance between surfaces for realistic occlusion
  - **Streetscape Geometry** - Interact with building and terrain geometry
  - **Scene Semantics** - ML-based understanding of surroundings (can identify sky, ground, buildings, vegetation)
  - **Geospatial API** - Attach content to GPS coordinates (useful for large yard layouts)
  - **Cloud Anchors** - Persist AR content across sessions and users
  - **Light Estimation** - Realistic lighting matches for placed objects
- **Relevance to Yard Objects:** HIGH - Plane detection enables placing fences on ground, pools on flat surfaces; Scene Semantics can distinguish grass/soil/patio; Geospatial API enables persistent location-based placement

### 2. Apple ARKit (iOS)
- **Not open-source** (proprietary to Apple), but essential ecosystem
- **Key Features:** Plane detection, object occlusion, people occlusion, LiDAR support, world tracking
- **Relevance:** HIGH - If targeting iOS, ARKit is the standard for AR experiences

### 3. SceneView (Cross-platform)
- **Repo:** https://github.com/sceneview/sceneview (1.2k stars)
- **Language:** Kotlin (Android), Swift (iOS)
- **Key Features:**
  - **3D & AR SDK** for Android (Jetpack Compose + Filament) and iOS (SwiftUI + RealityKit)
  - **AI-first** approach with MCP server, Copilot rules
  - Handles 3D model rendering, AR session management
  - Supports glTF/GLB models
- **Relevance:** HIGH - Modern, actively maintained (updated 2026-05-17), cross-platform, supports placing 3D models in AR scenes; best candidate for building a yard-object placement app

### 4. Sceneform (Android) - Maintained Fork
- **Repo:** https://github.com/sceneview/sceneform-android (679 stars)
- **Language:** Java/Kotlin
- **Key Features:** ARCore wrapper with 3D rendering via Google Filament; supports augmented images, augmented faces
- **Relevance:** MEDIUM - Successor to Google's archived Sceneform; good for Android AR with 3D object placement

### 5. AR.js (Web)
- **Repo:** https://github.com/AR-js-org/AR.js (5.9k stars)
- **Language:** JavaScript
- **Key Features:** Image tracking, location-based AR, marker tracking; runs in browser
- **Relevance:** MEDIUM - Good for web-based AR experiences; location-based AR could display yard objects at GPS coordinates, but limited compared to native for realistic placement

### 6. MindAR.js (Web)
- **Repo:** https://github.com/hiukim/mind-ar-js (2.7k stars)
- **Language:** JavaScript
- **Key Features:** Image tracking, face tracking; Tensorflow.js integration
- **Relevance:** LOW-MEDIUM - More focused on face filters and image tracking, less suited for outdoor yard placement

### 7. Google Model Viewer (Web)
- **Repo:** https://github.com/google/model-viewer (8.1k stars)
- **Language:** TypeScript/Web Components
- **Key Features:** Display 3D models on web, integrated AR quick-look for iOS and AR scene form for Android
- **Relevance:** MEDIUM - Great for previewing 3D models of yard objects (fences, pools) on web pages with "View in AR" button; not a full placement solution

### 8. A-Frame (WebVR/AR)
- **Repo:** https://github.com/aframevr/aframe (17.5k stars)
- **Language:** JavaScript
- **Key Features:** Web framework for building VR/AR experiences; entity-component architecture
- **Relevance:** MEDIUM - Can be combined with AR.js for web-based AR yard visualization

---

## Specialized / Demo Projects

### 9. CamAR
- **Repo:** https://github.com/hooverti/CamAR (3 stars)
- **Language:** Swift
- **Key Features:** Simple ARKit app demonstrating **plane detection and object placement/tracking**
- **Relevance:** HIGH (conceptually) - Directly demonstrates the core interaction needed for yard objects: detect a surface (ground/patio) and place a 3D object on it. Useful as a reference implementation for the basic interaction pattern.

### 10. Google AR Drawing (Java)
- **Repo:** https://github.com/googlecreativelab/ar-drawing-java (412 stars)
- **Language:** Java
- **Key Features:** Simple AR drawing using ARCore
- **Relevance:** LOW - Drawing-focused, but shows ARCore integration pattern

### 11. Google Creative Lab - Norman AR
- **Repo:** https://github.com/googlecreativelab/norman-ar (139 stars)
- **Key Features:** "Decorate your world with AR animations"
- **Relevance:** LOW-MEDIUM - Decorative/animation focused, not object placement per se

### 12. ARKit-CoreLocation
- **Repo:** https://github.com/AndrewHartAR/ARKit-CoreLocation (5.5k stars)
- **Language:** Swift
- **Key Features:** Combines AR accuracy with GPS scale
- **Relevance:** MEDIUM-HIGH - Could be used to place yard objects at specific GPS coordinates in outdoor environments; location persistence for large yard layouts

### 13. ViroReact / ReactVision Viro
- **Repo:** https://github.com/ReactVision/viro (1.8k stars)
- **Language:** Java/React Native
- **Key Features:** AR and VR using React Native and Expo
- **Relevance:** MEDIUM - Cross-platform AR/VR framework; supports object placement in AR scenes

---

## Google ARCore - Specific APIs for Yard Object Placement

| API | Use for Yard Objects |
|-----|---------------------|
| **Motion Tracking** | Track device position as user walks around yard |
| **Environmental Understanding** | Detect ground planes (grass, patio, concrete) for placing fences, pools |
| **Depth API** | Occlusion when placing tall objects (fences behind trees) |
| **Scene Semantics** | Identify lawn vs. patio vs. driveway to suggest appropriate objects |
| **Geospatial API** | Place objects at real-world GPS coordinates; persist across sessions |
| **Streetscape Geometry** | Interact with existing building/terrain geometry |
| **Cloud Anchors** | Share yard designs with contractors/family |
| **Light Estimation** | Realistic lighting on placed objects |

---

## Commercial Closed-Source References (for design inspiration)

These apps demonstrate the concept but are NOT open-source:

| App | Platform | Yard Objects? |
|-----|----------|---------------|
| **IKEA Place** | iOS/Android | Furniture-focused, but similar placement UX |
| **Houzz View in My Room** | iOS/Android | Home decor; similar AR placement |
| **Planner 5D** | iOS/Android/Web | Floor plans + AR view |
| **iScape** (Yard-specific) | iOS | **Directly relevant** - landscape design with AR, but closed source |
| **Home Outside** | iOS | Yard/landscape design, AR preview |
| **Hover** | iOS/Android | 3D property measurements with AR |

---

## Technology Stack Recommendation for Building an Open-Source Yard AR System

### Core Technology Choices

| Component | Recommended Technology | Alternatives |
|-----------|----------------------|-------------|
| **Mobile AR Engine** | SceneView (Android/iOS) | ARKit raw, ARCore raw |
| **Web AR Preview** | Three.js + WebXR | A-Frame + AR.js |
| **3D Model Format** | glTF/GLB | USDZ (iOS only) |
| **Ground Detection** | ARCore Plane Detection | ARKit Plane Detection |
| **Semantic Understanding** | ARCore Scene Semantics | Custom ML model |
| **Location Persistence** | ARCore Geospatial API | ARKit CoreLocation |
| **3D Models of Yard Objects** | Custom glTF models | Sketchup models, free 3D asset stores |
| **Backend/Cloud** | Firebase + Cloud Anchors | Custom backend |

### Architecture Sketch
```
┌─────────────────────────────────┐
│         Mobile App              │
│  ┌──────────┐  ┌─────────────┐ │
│  │ AR View  │  │  Catalog    │ │
│  │(SceneView│  │ (Fence,     │ │
│  │  /ARKit) │  │  Pool, etc) │ │
│  └────┬─────┘  └──────┬──────┘ │
│       │                │        │
│  ┌────▼───────────────▼────┐    │
│  │    Placement Engine     │    │
│  │  - Plane detection      │    │
│  │  - Hit testing           │    │
│  │  - Scale/rotation        │    │
│  │  - Physics collision     │    │
│  └────┬───────────────┬─────┘    │
│       │               │          │
│  ┌────▼──────┐  ┌────▼──────┐  │
│  │ ARCore/   │  │ Geospatial│  │
│  │ ARKit     │  │    API    │  │
│  └───────────┘  └───────────┘  │
└─────────────────────────────────┘
│
│  ┌─────────────────────────────┐
│  │     Cloud Backend           │
│  │  - User designs/sessions    │
│  │  - 3D model repository      │
│  │  - Cloud Anchors            │
│  └─────────────────────────────┘
```

---

## Key Challenges for Yard Object AR Specifically

1. **Outdoor Lighting:** AR tracking is harder outdoors due to variable lighting, glare, and lack of textured surfaces (lawns are featureless)
2. **Large Scale:** Yard objects are large (fences span 50+ feet); AR drift becomes noticeable at scale. Geospatial anchoring helps.
3. **Ground Plane Differentiation:** Need to distinguish between lawn, patio, driveway, soil - Scene Semantics helps but isn't perfect
4. **3D Model Sourcing:** High-quality glTF models of fences, pools, pergolas, sheds, etc. are needed. Free options are limited.
5. **Measurement Accuracy:** Users want to know "Will this 16ft pool fit here?" - ARCore/ARKit measurement is ~1-2% error, sufficient for rough planning
6. **Terrain Contours:** Flat ground is easy; slopes require topographic understanding, which standard AR plane detection doesn't handle well

---

## Summary

There is **no existing open-source project specifically for AR yard object placement**. The closest building blocks are:

1. **SceneView** - Best starting point for a modern cross-platform AR object placement app
2. **ARCore** (with Plane Detection, Depth API, Scene Semantics, Geospatial) - The most capable backend for outdoor AR
3. **CamAR** - Minimal reference implementation for plane detection + object placement
4. **AR.js / A-Frame** - Web-based alternative for simpler indoor/outdoor visualizations
5. **Model Viewer** - For web-based 3D preview with "View in AR" one-click launch

To build an open-source yard AR system, one would combine SceneView/mobile AR SDK + custom glTF yard object models + plane detection + Geospatial persistence.