---
created: 2026-05-03
tags: [project, task]
---

# POC plan — fence into yard, 2D only

## Goal

Prove the **2D pipeline end-to-end on one real photo pair** before building any UI, AR, or product abstractions.

Input → output, on the command line:

```
poc backyard.jpg fence.jpg "wooden picket fence along back of yard" → out.png
```

Out of scope for this POC: AR, image-to-3D, web UI, multi-tenant, auth, billing.

## Success criteria

A reviewer looking at `out.png` next to `backyard.jpg` says:

1. The fence is in the right place (sits on the ground, not floating, roughly correct scale).
2. The fence looks like the reference fence (not a generic AI hallucination).
3. Trees / foreground that *should* occlude the fence still occlude it.
4. Lighting and shadow direction match the scene well enough to not feel pasted.

If 1+2 work but 3 or 4 fail, that's still a green light — those are tractable polish steps. If 1 or 2 fail, the chosen vendor is wrong and we re-pick.

## Deliverables

- `src/ai_edit/providers/replicate.py` — thin Replicate client (Grounded-SAM + SAM 2)
- `src/ai_edit/providers/gemini.py` — thin Gemini Image client
- `src/ai_edit/pipeline/insert.py` — orchestration: image → masks → composite
- `scripts/poc.py` — CLI that runs the whole thing on two images
- `tests/fixtures/` — 2–3 backyard photos + 2–3 fence reference photos
- `out/` — generated composites + intermediate masks for inspection
- A short writeup in [[poc-results]] (created after first run)

## Milestones

### M1 — Skeleton & auth (½ day)
- [ ] Add `replicate` and `google-genai` to `pyproject.toml`
- [ ] `.env` with `REPLICATE_API_TOKEN`, `GEMINI_API_KEY`
- [ ] `Replicate` and `Gemini` provider classes following the `MiniMax` / `ZhipuAI` pattern already in `src/ai_edit/providers/`
- [ ] Smoke test: each provider returns a non-error response on a trivial call

### M2 — Segmentation (½ day)
- [ ] `segment(image, prompts)` on the Replicate provider — calls Grounded-SAM, returns one binary mask per prompt
- [ ] Save each mask as PNG into `out/masks/` for visual inspection
- [ ] Verify masks for `"ground"`, `"trees"`, `"sky"` on a real backyard photo

### M3 — Insertion (1 day)
- [ ] `compose(scene, reference, mask, instruction)` on the Gemini provider — multi-image edit
- [ ] First pass: pass scene + reference + mask + a prompt. Save raw output.
- [ ] Iterate on the prompt until criterion 1+2 pass on at least one fixture pair

### M4 — Occlusion polish (½ day, only if M3 passes)
- [ ] After Gemini returns the composite, re-paste foreground occluders (trees mask from M2) on top using PIL — guarantees occlusion criterion 3
- [ ] Compare with/without to confirm it actually helps

### M5 — Lighting polish (½ day, only if M3 passes)
- [ ] Pipe the composite through fal.ai IC-Light with a sun-direction prompt inferred from the original scene
- [ ] A/B against raw Gemini output

### M6 — Writeup (½ day)
- [ ] Capture 3 input pairs and their outputs in [[poc-results]]
- [ ] Decision: ship to UI? Or swap a provider? Or rethink?

**Total: ~3 working days.**

## Repo layout (target)

```
image-ai-edit/
├── pyproject.toml
├── .env.example
├── src/ai_edit/
│   ├── providers/
│   │   ├── replicate.py      # NEW — Grounded-SAM, SAM 2
│   │   ├── gemini.py         # NEW — Gemini 2.5 Flash Image
│   │   ├── falai.py          # later — IC-Light
│   │   ├── minimax.py        # existing
│   │   └── zhipuai.py        # existing
│   └── pipeline/
│       ├── __init__.py
│       └── insert.py         # NEW — orchestrator
├── scripts/
│   └── poc.py                # NEW — CLI entry
├── tests/
│   └── fixtures/             # NEW — sample backyard + fence images
└── out/                      # gitignored
    ├── masks/
    └── composites/
```

## Open decisions before writing code

- **Mask source for Gemini.** Gemini doesn't take a literal mask channel — only multi-image + prompt. Two options:
  1. Pass the binary mask as one of the input images and reference it in the prompt ("the white area in image 3 is where the fence goes").
  2. Don't pass the mask; let Gemini infer the location from the scene + prompt.
  Test both in M3 and pick. If neither works, swap insertion to **OpenAI gpt-image-1**, which has explicit `mask` input.

- **Whether to refine masks with SAM 2.** Skip in POC. Re-evaluate when we add a UI with click input.

- **Image sizes.** Cap inputs at 1024 px on long edge for the POC — keeps cost and latency low, makes side-by-side comparison easier.

## Risks / things that will probably go wrong

- Gemini ignores the reference fence's texture and synthesizes a generic fence → swap to FLUX.1 Kontext Pro.
- Mask leaks into the sky or a tree → tighten the prompt or stack a SAM 2 refine.
- Output looks pasted (no shadow on the ground) → IC-Light pass; if still bad, ask Gemini for a second pass with "add ground shadow under the fence consistent with sun direction".
- Replicate cold start latency on Grounded-SAM → cache the warmed model by hitting it once at process start.

## Linked notes

- [[stack-decision]] — why these vendors
- [[api-catalog]] — fallback options if a provider underperforms
- [[open-questions]] — known unknowns

#task #project