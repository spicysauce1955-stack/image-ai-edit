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

### Optional: AR / three.js agent skills

If you're working on the AR live page (`/ar/<id>/live`), install the
three.js Agent Skills subset so Claude Code has the relevant API
knowledge on hand:

```bash
.venv/bin/python scripts/fetch_skills.py          # default subset
.venv/bin/python scripts/fetch_skills.py --list   # see all upstream modules
```

These install into `.claude/skills/` (gitignored — instruction-only
Markdown from CloudAI-X/threejs-skills, which ships no license, so we
fetch rather than vendor). Restart Claude Code to pick them up.

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

## AR delivery (Phase 1)

The web server exposes `/ar/<scene-id>` for `<model-viewer>` + native AR
handoff. Phase 1 only serves pre-placed assets — drop a GLB at
`out/scenes/<scene-id>/model.glb` (and optionally a USDZ alongside) and
hit the URL from a phone.

### Quick manual smoke

```bash
# 1. Seed a known-good demo (Khronos Box ~3 KB)
.venv/bin/python scripts/fetch_ar_demo.py            # writes out/scenes/demo/model.glb

# 2. Start the server
.venv/bin/python scripts/serve.py                    # http://127.0.0.1:8000

# 3. From your phone on the same LAN:
#    http://<your-laptop-ip>:8000/ar/demo
```

Expected:
- 3D preview rotates on the page.
- On Android: "View in your space" → Scene Viewer launches → place the
  box in your camera view.
- On iOS: Quick Look will say "AR not supported" until you drop a
  USDZ at `out/scenes/demo/model.usdz`. Phase 2 will automate this.

### HTTPS for phone testing (Cloudflare Tunnel)

> **Full walkthrough**: [`https-tunnel-guide.md`](./https-tunnel-guide.md).
> Section below is the quick reference.

Phase 6.A's `/ar/<id>/live` page uses WebXR, which browsers gate
behind a [secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts).
`localhost` is exempt — your laptop's own browser is fine over plain
HTTP — but a phone hitting `http://<laptop-ip>:8000` is not, and
`navigator.xr` is silently `undefined`.

The fix is to expose the dev server over a real HTTPS URL.
We use [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
in "Quick Tunnel" mode — no Cloudflare account, no local certs, no
phone-side root-CA install. `cloudflared` opens a public
`https://<words>.trycloudflare.com` URL that proxies to your
`localhost:8000`. The URL rotates per session.

#### One-time setup

Install `cloudflared` (system binary, not a pip dep):

- **macOS:** `brew install cloudflared`
- **Linux (Debian/Ubuntu):**
  ```bash
  curl -L https://pkg.cloudflare.com/cloudflared-stable-linux-amd64.deb \
    -o /tmp/cloudflared.deb && sudo dpkg -i /tmp/cloudflared.deb
  ```
- **Windows:** `winget install --id Cloudflare.cloudflared`

#### Per-run (two terminals)

Terminal 1 — the app server:

```bash
.venv/bin/python scripts/serve.py        # http://127.0.0.1:8000
```

Terminal 2 — the tunnel:

```bash
.venv/bin/python scripts/dev_tunnel.py   # prints public HTTPS URL
```

Watch terminal 2 for a banner like:

```
============================================================
 PUBLIC URL:  https://swift-banana-grove-x42.trycloudflare.com

 Phone test (Android Chrome — WebXR):
   https://swift-banana-grove-x42.trycloudflare.com/ar/chainlink_fence/live
 ...
```

Open one of the printed URLs on the phone. No browser warning, the
lock icon is solid, `navigator.xr` is defined on WebXR-capable
browsers (Android Chrome; iOS Safari WebXR is still unavailable
upstream — iPhones fall back to Quick Look via `/ar/<id>`).

#### Privacy note

The Quick Tunnel URL is **publicly accessible** while the tunnel is
up. Don't post screenshots of the URL if you want to keep dev
session details private. Sessions are typically minutes-to-hours and
each restart of `dev_tunnel.py` rotates the URL.

#### Troubleshooting HTTPS

- **`cloudflared: command not found`** — `dev_tunnel.py` exits 127
  with a platform hint. Re-read the install step.
- **Public URL stays at 502** — the app server didn't start. Check
  terminal 1; the tunnel forwards blindly.
- **URL rotated** — restart `dev_tunnel.py`; the old URL is dead.
- **WebXR still "Not Supported" on the phone** — confirm you're on
  Android Chrome (iOS Safari WebXR isn't shipped upstream). If on
  Android: check Chrome → Settings → Site Settings → AR (most AR-
  capable devices have this on by default).
- **iOS Quick Look fails on a GLB-only entry** — that's expected;
  the catalog entry needs a `usdz_url`. The `teapot` entry has one
  for confirming the iOS path works.
- **Need a stable URL** — upgrade to a Cloudflare Named Tunnel
  (requires a Cloudflare account); out of scope here.

### Troubleshooting AR

- **Page 404s** — no asset exists for that `scene-id`. The store only
  considers a scene "to exist" once at least one asset is written.
- **Android AR button missing** — confirm GLB MIME with
  `curl -I http://localhost:8000/ar/demo/model.glb` (should say
  `model/gltf-binary`).
- **iOS AR button missing** — no `model.usdz` present (expected pre-Phase-2).
- **Scene ID rejected with 422** — the path-param regex is
  `[A-Za-z0-9_-]{1,64}`. Dots, slashes, spaces are blocked on purpose
  (path-traversal defence).

## Cost per run (rough)

| Step | Cost |
|---|---|
| Grounded-SAM (only with `--segment`) | ~$0.0014 |
| Gemini 2.5 Flash Image edit | ~$0.03–0.04 |
| **Total** | **~$0.03–0.05** |

See [stack-decision.md](./stack-decision.md) for the full pricing sketch including future steps.
