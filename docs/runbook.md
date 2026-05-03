# Runbook

How to actually run the POC, troubleshoot it, and read its output.

## First-time setup

```bash
cd ~/Workspace/image-ai-edit

# 1. Install the package (editable) into the existing venv
uv pip install -p .venv/bin/python -e .

# 2. Drop your keys in .env (copy .env.example if .env doesn't exist)
cp .env.example .env
# then edit .env and fill in:
#   GEMINI_API_KEY            (required)
#   REPLICATE_API_TOKEN       (only needed if you pass --segment)
#   FAL_KEY                   (only needed once IC-Light is wired in)

# 3. Drop two images at the repo root (or anywhere)
#   scene.jpg     — the photo to edit into
#   fence.jpg     — the reference object to insert
```

## Running the POC

### Minimum (Gemini key only)

```bash
.venv/bin/python scripts/poc.py scene.jpg fence.jpg \
  "place this fence along the back edge of the lawn"
```

Output: `out/composites/<timestamp>.png`.

### With segmentation

```bash
.venv/bin/python scripts/poc.py scene.jpg fence.jpg \
  "place this fence along the back edge of the lawn" \
  --segment "ground,trees,sky"
```

Additional output: `out/masks/<timestamp>-<label>.png` for each label that produced a mask. These are **not** fed back into Gemini in M3 — they're for inspection only. See [poc-plan.md](./poc-plan.md) for what they enable in later milestones.

### Custom output directory

```bash
.venv/bin/python scripts/poc.py scene.jpg fence.jpg "..." --out runs/exp1
```

Useful for keeping experiments side-by-side.

## What success looks like

Per [poc-plan.md](./poc-plan.md), eyeball the composite against four criteria:

1. Fence is in the right place (sits on ground, plausible scale).
2. Fence looks like the *reference* (texture, slat width, colour).
3. Trees / foreground that should occlude the fence still occlude it.
4. Lighting & shadow direction roughly match the scene.

If 1+2 pass we've validated the vendor pick. If 3 or 4 fail those are tractable polish steps (M4 / M5).

## Troubleshooting

### `EnvironmentError: Missing required env var: GEMINI_API_KEY`
`.env` not loaded or key not set. Check that `.env` lives at the repo root (the CLI calls `load_env()` against `cwd/.env`) and that the line reads `GEMINI_API_KEY=...` with no quotes.

### `RuntimeError: Gemini returned no image. Text: '...'`
Gemini ran but only returned text — usually a policy refusal. The error includes the first 200 chars of Gemini's text response, which usually explains what to change. Try softening the prompt, or check the safety/content of the input images.

### `httpx.HTTPStatusError: 401`
- On a Replicate URL → bad `REPLICATE_API_TOKEN`.
- On a `generativelanguage.googleapis.com` URL → bad `GEMINI_API_KEY`.
- On a `fal.run` URL → bad `FAL_KEY`.

### `TimeoutError: Replicate prediction timed out after 120.0s`
Grounded-SAM hung. Re-run; if it persists, increase `POLL_TIMEOUT_S` in `providers/replicate.py` or check Replicate's status page.

### `httpx.HTTPStatusError: 404` on a Replicate model URL
Model identifier may have moved. Check that `GROUNDED_SAM_MODEL = "schananas/grounded_sam"` still resolves at https://replicate.com/schananas/grounded_sam.

### Composite looks pasted (no shadow under the fence)
Expected for the bare M3 pipeline. Wire in M5 (fal.ai IC-Light) or add an explicit "cast a ground shadow under the fence consistent with the scene's sun direction" sentence to the instruction.

### Composite invents a generic fence instead of using the reference
The vendor isn't honoring the reference image strongly enough. Two options:
- Strengthen the prompt: "Use the **exact** fence in image 2 — preserve its slat shape, colour, and material. Do not invent a different fence."
- Swap insertion to FLUX.1 Kontext Pro (see [contributing.md](./contributing.md) for the recipe).

### `out/` already has files from a previous run
That's by design — runs are timestamp-prefixed so they accumulate. Delete the directory if you want a clean slate. `out/` is gitignored.

## Reading the output

```
out/
├── composites/
│   ├── 20260503-141522.png   # most recent run
│   └── 20260503-140801.png
└── masks/
    ├── 20260503-141522-ground.png
    ├── 20260503-141522-trees.png
    └── 20260503-141522-sky.png
```

Mask PNGs are typically white-on-black; open one and overlay it on the scene in any image editor to confirm the segmentation hit the right region.

## Cost per run (rough)

| Step | Cost |
|---|---|
| Grounded-SAM (only with `--segment`) | ~$0.0014 |
| Gemini 2.5 Flash Image edit | ~$0.03–0.04 |
| **Total** | **~$0.03–0.05** |

See [stack-decision.md](./stack-decision.md) for the full pricing sketch including future steps.
