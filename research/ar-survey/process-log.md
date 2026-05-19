# Process Log — AR Survey

Chronological record of research moves, sources hit, and observations. Newest entries appended at the bottom.

---

## 2026-05-18 — Kickoff

**Goal:** Map the AR landscape for web + phone, with enough depth that a follow-up implementation task can pick a stack confidently.

**Plan:**
1. Build directory scaffolding + this log.
2. Run parallel deep-research queries on (a) Web AR frameworks, (b) native mobile SDKs, (c) cross-platform frameworks, (d) methodologies/techniques, (e) supporting tech stack.
3. Drill into anything surprising with targeted searches/extracts.
4. Synthesize into a comparison matrix and per-use-case recommendations.

**Prior art in repo:** `../ar-yard-objects-research.md` — narrow, open-source-only, yard-object placement focus. Will reference rather than duplicate.

**Sources to prioritize:**
- Official docs (developer.apple.com, developers.google.com/ar, immersive-web.github.io)
- Framework homepages (aframe.io, ar-js-org, mind-ar-js, 8thwall.com, niantic.dev, threejs.org)
- Recent comparisons (state-of-webxr type articles from 2025–2026)

**Logging conventions:**
- Each query gets: query string, tool, top hits, what I kept.
- Decisions / pivots get their own dated entry.
- URLs go into the relevant subfolder note, not this log, to keep it scannable.

---

## 2026-05-18 — Round 1 results

Fired 5 parallel `tavily_research pro` calls (Web AR, Native Mobile, Cross-platform, Methodologies, Tech Stack).

- **Web AR**: returned, 200+ pages of structured findings, 55 sources. Written to `01-web-ar/findings.md`.
- **Native Mobile**: returned, 35 sources. Written to `02-mobile-ar/findings.md`.
- **Cross-platform**: **failed** — Tavily `getaddrinfo ENOTFOUND api.tavily.com` (transient DNS / rate-limit on parallel calls).
- **Methodologies**: **failed** — same DNS error.
- **Tech Stack**: **failed** — same DNS error.

**Decision:** Save round-1 wins to disk first (so they're not lost if the session compresses), then re-run the three failed streams — sequentially this time to avoid hammering the upstream.

**Notable findings from round 1 (one-liners, full detail in subfolder notes):**
- 8th Wall hosted platform retired 28 Feb 2026; engine + tools released free. Existing experiences run until Feb 2027. Major landscape shift.
- ARCore Geospatial billing/cost is *ambiguous* in Google's own docs (free per launch blog vs billing-required per SceneView samples). Flag for any production plan.
- SceneKit deprecated; new Apple AR work should target RealityKit 4 + USD.
- RoomPlan + Object Capture (area mode, WWDC '24) is the strongest indoor-scanning native pipeline.
- No Apple-provided cross-platform cloud-anchor service surfaced — Android↔iOS shared AR needs a third party (Niantic, Immersal) or custom server.

---

## 2026-05-18 — Round 2: retries completed

Re-ran the three failed streams **sequentially** (Tavily DNS errors on parallel calls seem to have been a transient/rate-limit issue).

- **Cross-platform** → success → `03-cross-platform/findings.md` (28 sources)
- **Methodologies** → success → `04-methodologies/findings.md` (45 sources)
- **Tech stack** → success → `05-tech-stack/findings.md` (38 sources)

**Notable findings from round 2:**
- **8th Wall hosted platform retired 28 Feb 2026**; engine + tools partially open-sourced (binary SLAM proprietary, framework MIT). Existing experiences run until Feb 2027.
- **Niantic Lightship ARDK 3.x repos deprecated** — go to `nianticspatial` org for 4.x+. Multiplayer free <50k MAU.
- **ViroReact alive again** — acquired Jan 2025 by Morrow Digital, now under ReactVision org. v2.54.0 Mar 2026. The recommended React Native AR path.
- **`expo-three-ar` unsupported** — Expo Go removed AR.
- **Flutter cross-platform AR is stagnant** — `ar_flutter_plugin` last release Nov 2022.
- **Godot 4.6 (Jan 2026)**: real OpenXR 1.1 + Spatial Entities + passthrough. Khronos-loader APK enables one-binary multi-device builds.
- **ARKit slanted plane alignment** since WWDC 2024 — in addition to horizontal/vertical.
- **Gaussian Splatting** is reaching mobile feasibility (Mobile-GS); production capture via Polycam/Luma AI/KIRI/Scaniverse (vendor docs not in corpus, verify directly).
- **WebGPU + ONNX Runtime Web** is the new high-perf path for browser ML inference.
- **Azure Spatial Anchors** known to be deprecated by Microsoft (Nov 2024 retirement) — flagged but not in evidence corpus.

**Next:** synthesize comparison matrix + per-use-case recommended stacks in `06-synthesis/`.

