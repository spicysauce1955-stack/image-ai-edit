---
created: 2026-05-20
tags: [guide, ar, https]
---

# HTTPS tunnel guide — phone-testing the AR pipeline

Walks you from a clean clone to a working phone test of the AR
pipeline (`/ar/<id>`, `/ar/<id>/live`, `/catalog`) over real HTTPS.

If you only need a refresher on the commands, the quick-reference
version lives in [`runbook.md → HTTPS for phone testing`](./runbook.md#https-for-phone-testing-cloudflare-tunnel).
This document is the full walkthrough.

---

## Why we need a tunnel at all

The Phase 6 live AR page (`/ar/<id>/live`) uses the [WebXR Device
API](https://developer.mozilla.org/en-US/docs/Web/API/WebXR_Device_API).
Browsers gate WebXR behind a *secure context*: `https://` or
`http://localhost`. A phone hitting `http://192.168.1.5:8000` over
LAN is neither — `navigator.xr` is silently `undefined` and the
"START AR" button reports "AR NOT SUPPORTED".

We get a real HTTPS URL the cheap way: [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
in **Quick Tunnel mode**. `cloudflared` allocates a public
`https://<random-words>.trycloudflare.com` URL that proxies to
`http://localhost:8000`. No Cloudflare account, no local certs, no
phone-side trust setup. The URL rotates each session, which is fine
for dev.

> **Privacy.** While the tunnel is up, the URL is publicly reachable
> by anyone who learns it. Don't post screenshots of the URL.
> Cloudflare sees the traffic. Stop the tunnel when you're done.

---

## Prerequisites (one-time setup)

### 1. Repo + Python venv

```bash
cd ~/Workspace/image-ai-edit                              # or wherever you cloned it
uv pip install -p .venv/bin/python -e ".[dev,server,bundle]"
```

This installs the package in editable mode plus the dev (pytest),
server (FastAPI + uvicorn), and bundle (pygltflib for the asset
bundler) extras. Run `pytest tests/` to confirm — should see ~194
passing tests + 2 network-gated skips.

### 2. `cloudflared`

System binary, not a pip dep. Pick the one for your OS:

**macOS:**

```bash
brew install cloudflared
```

**Linux (Debian / Ubuntu):**

```bash
curl -L https://pkg.cloudflare.com/cloudflared-stable-linux-amd64.deb \
  -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
```

**Linux without sudo** (or any Linux where dpkg isn't your style):

```bash
mkdir -p ~/.local/bin
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.local/bin/cloudflared
chmod +x ~/.local/bin/cloudflared
# make sure ~/.local/bin is on PATH — most distros do this automatically
```

**Windows:**

```powershell
winget install --id Cloudflare.cloudflared
```

Verify with:

```bash
cloudflared --version
# cloudflared version 2026.x.x (...)
```

### 3. Seed the AR catalog

The AR routes serve assets out of `out/scenes/<id>/`. The first time,
download the curated catalog so there's something to see:

```bash
.venv/bin/python scripts/fetch_catalog.py --all
```

You should see something like:

```
box              ✓ GLB (1.6 KB)   – USDZ
duck             ✓ GLB (117.7 KB)   – USDZ
damaged_helmet   ✓ GLB (3.6 MB)   – USDZ
boombox          ✓ GLB (10.1 MB)   – USDZ
lantern          ✓ GLB (9.1 MB)   – USDZ
antique_camera   ✓ GLB (16.7 MB)   – USDZ
teapot           – GLB   ✓ USDZ (8.6 MB)
chainlink_fence  ✓ GLB (8.2 MB)   – USDZ
planter_box      ✓ GLB (2.9 MB)   – USDZ
clay_pot         ✓ GLB (2.3 MB)   – USDZ
gate_latch       ✓ GLB (2.6 MB)   – USDZ
```

Total disk: ~50 MB. Stored in `out/scenes/`, which is gitignored.

---

## Per-session run (two terminals)

You'll have two foreground processes. Use two terminals (or a
terminal multiplexer; tmux/screen are fine).

### Terminal 1 — the app server

```bash
cd ~/Workspace/image-ai-edit
.venv/bin/python scripts/serve.py
```

You should see uvicorn boot output ending with:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Sanity-check locally before involving the tunnel:

```bash
curl -s http://127.0.0.1:8000/healthz
# {"status":"ok"}
```

Leave this terminal running. Restart only if you change Python code.

### Terminal 2 — the HTTPS tunnel

```bash
cd ~/Workspace/image-ai-edit
.venv/bin/python scripts/dev_tunnel.py
```

You'll see:

```
==> starting Cloudflare Quick Tunnel  →  http://localhost:8000
    (waiting for cloudflared to allocate a public URL…)
```

Within a few seconds, cloudflared connects to its edge and a banner
appears:

```
============================================================
 PUBLIC URL:  https://words-words-words-words.trycloudflare.com

 Phone test (Android Chrome — WebXR):
   https://words-words-words-words.trycloudflare.com/ar/chainlink_fence/live

 Phone test (iOS Safari — Quick Look):
   https://words-words-words-words.trycloudflare.com/ar/teapot

 Catalog browser:
   https://words-words-words-words.trycloudflare.com/catalog

 Tunnel proxies to:  http://localhost:8000
============================================================
```

Copy one of those URLs to your phone (AirDrop / Messages / a QR-
code generator / type it). Restart **only** when you want a new
URL — each restart picks a new random hostname.

---

## Testing on a phone

The catalog has three categories of entries relevant for testing:

| Category | Best on | Why |
|---|---|---|
| `fence`, `planter`, `outdoor` (Poly Haven GLBs) | Android Chrome → live WebXR | The yard-relevant content. GLB only. |
| `decor → teapot` (Apple USDZ) | iPhone Safari → Quick Look | USDZ-native, confirms iOS path. |
| `sample` (Khronos) | Either; smallest are useful for first smoke | Box / Duck are tiny and load fast. |

### Android Chrome — WebXR live placement

Open on your phone:

```
https://<your-tunnel-host>/ar/chainlink_fence/live
```

What to expect:

1. Page loads, a 3D fence rotates against a dark background (the
   non-AR preview, orbit-control-driven — drag to look around).
2. Bottom-right panel: model dropdown, scale slider, rotate-Y
   slider, reset button. Touch them; the preview reacts live.
3. Bottom-centre white pill: **"START AR"**.
4. Tap "START AR". Chrome asks for camera permission. Allow it.
5. Camera view opens. Move the phone slowly to scan a flat surface
   (floor, table). A small white reticle appears once a plane is
   detected.
6. **Tap anywhere** in the camera view — the fence appears at the
   reticle's location, anchored to the real-world surface. Walk
   around it; it stays put.
7. Tap again with the reticle visible to move the fence to a new
   spot. The scale and rotation sliders still work in AR.
8. End the session via Chrome's "X" / system back. The non-AR
   preview returns.

If the AR button says "AR NOT SUPPORTED" — see Troubleshooting.

### iPhone Safari — Quick Look

Open:

```
https://<your-tunnel-host>/ar/teapot
```

This is the `<model-viewer>` page, not the WebXR `/live` page —
iOS Safari has no WebXR, so we don't use `/live` on iPhones.

1. Page loads, teapot rotates.
2. Tap **"View in your space"** in the bottom-right.
3. Quick Look takes over. The teapot appears anchored to a surface
   in your environment. Drag to move it; pinch to scale; rotate
   with two fingers.
4. Done button returns to the page.

For GLB-only catalog entries on iOS (`chainlink_fence`,
`planter_box`, etc.), `/ar/<id>` still shows the 3D preview but
the AR button will say "AR not supported" — those entries don't
have a USDZ. The `teapot` entry is the one wired up for iOS.

### Catalog browser

```
https://<your-tunnel-host>/catalog
```

A grid of all 11 catalog entries with thumbnails and "View in AR"
buttons. Tap any card → goes to `/ar/<id>`. Useful for browsing on
either platform.

---

## Stopping everything

In each terminal, **Ctrl-C** stops the process cleanly:

- Terminal 2 (`dev_tunnel.py`) — the script catches the interrupt,
  terminates `cloudflared`, exits 0. The public URL goes dead
  immediately. Any phone still on the page sees a 502.
- Terminal 1 (`serve.py`) — uvicorn exits.

If you forget and want to kill orphan processes:

```bash
pgrep -af "scripts/serve.py|dev_tunnel.py|cloudflared" \
  | grep -v grep | awk '{print $1}' | xargs -r kill
```

---

## Day 2: what changes when you come back tomorrow

- **Same machine, same setup** — `cloudflared` is already
  installed, the catalog is already on disk. Just run the two
  terminal commands. The new public URL will be different from
  yesterday's; that's normal.
- **New machine** — go through "Prerequisites" again.
- **You changed a catalog entry** — re-run `fetch_catalog.py --id <changed>`.
  The serve.py picks up new disk content on every request; no
  restart needed.
- **You changed Python code** — restart `serve.py` (Ctrl-C, re-
  launch). The tunnel keeps running — same public URL, same proxy
  target.
- **You want auto-reload during dev** — `serve.py --reload`.

---

## Troubleshooting

### `cloudflared: command not found` when running `dev_tunnel.py`

The script prints platform-specific install hints and exits with
code 127 (shell convention for "command not found"). Re-read the
[Prerequisites → `cloudflared`](#2-cloudflared) section above and
confirm with `cloudflared --version`.

### Banner never appears (just the "waiting…" line forever)

Two common causes:

1. **Network blocks outbound to `*.trycloudflare.com`** — corporate
   networks sometimes filter it. Try a different network (phone
   hotspot is a fast test).
2. **`cloudflared` is stuck on an old version** — `cloudflared
   update` and retry, or re-download the latest binary per
   Prerequisites.

You should also see cloudflared's own log lines (timestamps with
`INF` markers). If you see those but no `https://...trycloudflare.com`
line, the protocol negotiation is failing — the cloudflared logs
will say why.

### Public URL returns 502 Bad Gateway

The tunnel is up but the app server isn't responding. Check
Terminal 1:

- Did `serve.py` print the "Uvicorn running on http://127.0.0.1:8000"
  line? If not, it hasn't started yet.
- Did it crash? Scroll up for tracebacks.
- Is it listening on a different port? `dev_tunnel.py` defaults
  to 8000 — if you ran `serve.py --port 8080`, pass `--port 8080`
  to `dev_tunnel.py` too.

Quick local sanity check: `curl http://127.0.0.1:8000/healthz`.
If that's 502 / refused, the issue is the server, not the tunnel.

### Public URL returns 200 but `/ar/<id>` is 404

The catalog asset for that scene id isn't on disk. Run
`scripts/fetch_catalog.py --id <id>` (or `--all`) to fetch it.

### Android: "AR NOT SUPPORTED" despite Chrome on a recent phone

Check, in order:

1. **You're on HTTPS, not the LAN HTTP fallback.** The URL bar
   should start with `https://` and the lock icon should be
   solid.
2. **AR-capable device.** ARCore-supported list:
   [developers.google.com/ar/devices](https://developers.google.com/ar/devices).
   Older / budget devices may not be on it.
3. **Google Play Services for AR installed.** Some phones don't
   ship it; install from the Play Store ("Google Play Services
   for AR").
4. **Chrome's AR permission.** Chrome → Settings → Site Settings
   → AR → ensure not blocked. Some Chromium variants (Samsung
   Internet etc.) have their own setting.

### iOS: "AR not supported" on `/ar/<id>`

If the entry has a USDZ (only `teapot` in the current catalog),
this shouldn't happen — Quick Look should engage. If it doesn't:

1. **You're on real Safari** (not Firefox / Chrome on iOS, which
   are all WebKit but with quirks).
2. **iOS 12+** — most current devices are fine.
3. **Real cert chain** — `https://<...>.trycloudflare.com` is a
   genuine Let's Encrypt cert; if Safari shows a warning, the
   tunnel isn't really serving over HTTPS (network issue?
   re-run `dev_tunnel.py`).

For GLB-only entries (`chainlink_fence`, etc.) the "AR not
supported" message is expected on iOS — those entries don't have
USDZ files. That's a content gap, not a bug.

### iOS: `/ar/<id>/live` says "AR NOT SUPPORTED"

Also expected. iOS Safari doesn't ship the WebXR Device API. Use
`/ar/<id>` (Quick Look) instead on iPhones.

### My phone is on cellular / different network than my laptop — does the tunnel work?

Yes, that's the whole point. The Quick Tunnel URL is reachable
from anywhere on the public internet. Your phone doesn't need to
be on the same Wi-Fi.

### URL rotated mid-session — old link 404s

When `dev_tunnel.py` restarts, it gets a fresh random URL. Make
sure your phone is on the *current* URL printed in the banner.

### I want a stable URL so I don't have to re-share

Quick Tunnels rotate by design. For a stable URL you need a
[Cloudflare Named Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/),
which requires a Cloudflare account and DNS setup. Out of scope
for `dev_tunnel.py`; document if you build it.

### I'm getting throttled / rate-limited

Quick Tunnels are explicitly best-effort and Cloudflare reserves
the right to investigate / limit them. For serious / repeated dev
work, move to a Named Tunnel.

---

## What's next

- **6.B → 6.C: touch gestures in AR.** Drag to move the placed
  model, pinch to scale, two-finger rotate. The HUD sliders are
  already wired; gestures would write to the same state object.
- **6.D: AR snapshot → photoreal 2D bridge.** Capture an AR frame
  with the placed virtual fence, feed it back through the existing
  2D `insert_object` pipeline as the scene image. Closes the loop
  the project hinted at from the start.
- **6.E: persistence.** localStorage today, cloud anchors later.

See [`ar-plan.md`](./ar-plan.md) for the full Phase 6 roadmap.
