---
created: 2026-05-03
tags: [project, idea]
---

# Open questions

Things to resolve during or right after the POC.

## Vendor / model

- Does Gemini 2.5 Flash Image actually preserve the reference fence's *exact* texture, or does it stylize? Decide between Gemini and FLUX.1 Kontext Pro after M3.
- For commercial launch: do we need the indemnified output of **Adobe Firefly** or **Bria**? Depends on go-to-market.
- Is **Replicate cold-start latency** acceptable for an interactive UX, or do we need fal.ai's faster regions?

## Pipeline

- Mask channel vs. multi-image-as-mask — which conditioning works best with Gemini? (Test in M3.)
- Do we need an explicit **depth map** step (Depth Anything v2 on Replicate) to enforce perspective, or does Gemini do it well enough from the scene alone?
- Should foreground occluders be **re-pasted post-hoc** (PIL composite over the AI output) or trusted to the model? Re-paste is more reliable; test both.

## AR / phase 2

- For Meshy Multi-Image-to-3D — what's the **minimum number of fence photos** to get a usable GLB? (Vendor docs don't say; need empirical test.)
- Does Android Scene Viewer expose **per-pixel occlusion** in a no-install browser flow on representative devices? Open question from research.
- For yards specifically: do we need **Geospatial API anchors** (ARCore) so the fence stays put across sessions, or is single-session placement enough?

## Product

- One-shot composite per request, or interactive multi-turn ("move it left, make it taller")? Multi-turn fits Gemini's chat-style edits well.
- Do we expose the segmentation masks to the user as an editable layer, or hide them entirely?

#idea #project