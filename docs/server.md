# Server

Thin FastAPI app wrapping :func:`ai_edit.pipeline.insert.insert_object`. Lets you drive the pipeline from a browser or any HTTP client instead of the CLI.

## Setup

```bash
uv pip install -p .venv/bin/python -e ".[server]"
```

The `server` extra installs FastAPI, uvicorn, and `python-multipart`. The core `ai_edit` package stays free of these so importing providers from another project doesn't pull in a web framework.

Make sure `.env` is in place — the server calls `load_env()` at startup, then providers are constructed lazily inside the pipeline as needed.

## Run

```bash
.venv/bin/python scripts/serve.py                    # http://127.0.0.1:8000
.venv/bin/python scripts/serve.py --host 0.0.0.0 --port 8080
.venv/bin/python scripts/serve.py --reload           # dev: auto-reload
```

Or directly:

```bash
.venv/bin/uvicorn ai_edit.server.app:app --reload
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Drag-drop upload UI |
| `GET` | `/static/*` | CSS / JS for the UI |
| `GET` | `/api/defaults` | Default system prompts for `free` / `mask` / `overlay` / `refine`. |
| `POST` | `/api/insert` | Run the pipeline. Returns a JSON envelope with one-shot URLs. |
| `GET` | `/api/result/{token}/composite.png` | Composite bytes referenced from the JSON above. |
| `GET` | `/api/result/{token}/aux.png` | Aux image bytes (mask or overlay) — only when the request used `mask` or `overlay` mode. |
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/docs` | Auto-generated OpenAPI docs |

### `POST /api/insert`

Multipart form. Required fields:

| Field | Type | Notes |
|---|---|---|
| `scene` | file | The scene photo |
| `reference` | file | The object to insert |
| `instruction` | string | Free-form edit description |

Optional fields:

| Field | Type | Notes |
|---|---|---|
| `mode` | string | `free` (default) / `mask` / `overlay`. Controls what (if anything) the server builds as image 3 to Gemini. `mask` and `overlay` require a polygon. |
| `polygon` | string | JSON list of normalized `[u, v]` vertices in `[0, 1]`, e.g. `[[0.05,0.4],[0.55,0.35],[0.55,0.85],[0.05,0.9]]`. ≥3 vertices required. |
| `system_prompt` | string | Override the mode's default system prompt. Empty = use the default for the active mode (see `GET /api/defaults`). |
| `previous` | file | A previous composite from this conversation. When set the call switches into refinement mode regardless of `mode`. |
| `segment` | string | Comma-separated labels for Grounded-SAM (e.g. `"ground,trees,sky"`). Empty = skip segmentation. |
| `relight` | string | IC-Light prompt. Empty = skip relight. Tends to restyle the inserted object — use sparingly. |

**Modes**

- `free` — no polygon used. Gemini chooses placement from the prompt + scene.
- `mask` — polygon → binary PNG (white = "place here", black = "preserve") sent to Gemini as image 3.
- `overlay` — polygon → a copy of the scene with the reference *pre-placed* inside the polygon (Pillow paste + polygon clip), sent to Gemini as image 3 to clean up. Useful when you want stronger spatial guidance than a flat mask.

Response: a JSON envelope.

```json
{
  "composite_url": "http://.../api/result/<token>/composite.png",
  "aux_url":       "http://.../api/result/<token>/aux.png",  // null when free / refine
  "aux_kind":      "mask" | "overlay" | null,
  "text":          ""                                         // any commentary from Gemini
}
```

The actual image bytes live in a process-local cache (capped at 64 entries, evicted FIFO) and are served from the URLs above. Tokens are random and not guessable. The cache evicts on process restart — if you need persistent results, save them client-side immediately.

Errors from upstream providers are surfaced as `502` with the exception message in the body. Bad polygon payloads return `400`.

### Example: curl

```bash
# basic
curl -sS -X POST http://127.0.0.1:8000/api/insert \
  -F "scene=@yard.png" \
  -F "reference=@fence.jpg" \
  -F "instruction=place this fence along the back edge of the lawn"
# → {"composite_url": "...", "mask_url": null, "text": ""}

# mask mode — polygon becomes a binary mask
curl -sS -X POST http://127.0.0.1:8000/api/insert \
  -F "scene=@yard.png" \
  -F "reference=@fence.jpg" \
  -F "instruction=place this fence inside the marked region" \
  -F "mode=mask" \
  -F 'polygon=[[0.05,0.4],[0.55,0.35],[0.55,0.85],[0.05,0.9]]'

# overlay mode — polygon becomes a pre-placed paste of the reference,
# Gemini's job is to blend it cleanly
curl -sS -X POST http://127.0.0.1:8000/api/insert \
  -F "scene=@yard.png" \
  -F "reference=@fence.jpg" \
  -F "instruction=blend the pre-placed fence into the scene" \
  -F "mode=overlay" \
  -F 'polygon=[[0.05,0.4],[0.55,0.35],[0.55,0.85],[0.05,0.9]]'

# custom system prompt override
curl -sS -X POST http://127.0.0.1:8000/api/insert \
  -F "scene=@yard.png" \
  -F "reference=@fence.jpg" \
  -F "instruction=put a fence here" \
  -F "mode=mask" \
  -F 'polygon=[[...]]' \
  -F "system_prompt=Image 1 is the scene. Image 2 is the reference object. Image 3 is a region mask. Place the object inside the white region only."

# follow up by fetching the URLs from the JSON response
```

### Example: Python

```python
import json, httpx

with open("yard.png", "rb") as scene, open("fence.jpg", "rb") as ref:
    r = httpx.post(
        "http://127.0.0.1:8000/api/insert",
        files={"scene": scene, "reference": ref},
        data={
            "instruction": "place this fence inside the marked region",
            "polygon": json.dumps([[0.05,0.4],[0.55,0.35],[0.55,0.85],[0.05,0.9]]),
        },
        timeout=120,
    )
r.raise_for_status()
env = r.json()
composite = httpx.get(env["composite_url"]).content
open("composite.png", "wb").write(composite)
```

## Design notes

- **Stateless.** Nothing is persisted on the server. Uploads land in a `tempfile.TemporaryDirectory` that's cleaned up before the response is sent. Composites are streamed straight back in the response body.
- **Synchronous from the client's POV.** The client gets one HTTP response when the whole pipeline finishes. Long-running jobs (notably IC-Light) hold the connection open. If we ever want true async, the natural pattern is to mirror fal.ai's queue endpoint: return `{job_id, status_url}` and let the client poll.
- **Errors as 502.** Any exception from `insert_object` becomes `502 Bad Gateway` because the API itself is fine — its upstream dependency failed. The exception message is in the response body.
- **No auth.** Trust-the-network for the local POC. Stick the server behind a reverse proxy with a token check before exposing it publicly.

## Web UI

The page at `/` is a deliberate zero-build single-page app. Three files in `src/ai_edit/server/static/`:

- `index.html` — markup only.
- `app.css` — design tokens (light/dark via `prefers-color-scheme`), two-column layout.
- `app.js` — drag-drop, generate, refine loop, attempt history.

Layout is two columns: **inputs** on the left (scene + reference drops, instruction, advanced segment/relight options); **result** on the right (canvas + in-place "Refine" box + history strip of every attempt). Click any history thumbnail to bring it back as the base for the next refinement.

After the scene is loaded, the drop turns into a polygon-drawing canvas — click on the image to add vertices, "Undo" / "Clear region" / "Replace" controls live in the block header. Vertices are stored in normalized image coordinates (`[u, v]` in `[0, 1]`) so window resizes during drawing don't invalidate them.

Below the inputs there are two configurable bits:

- **Mode** (Free / Mask / Overlay) as a segmented radio group. Mask + Overlay require a polygon and are validated client-side before submit.
- **System prompt** in a collapsible — pre-filled with the active mode's default (fetched once from `/api/defaults` at load), with a "Reset to default" button. The textarea tracks a `dirty` flag so changing modes only replaces the contents when the user hasn't edited it.

If we want a richer frontend (auth, multi-tenant, persisted history), this is the wrong layer to grow it from; build a separate frontend (Next.js etc.) and call `/api/insert` from there.

## Caveats

- File size isn't capped server-side. FastAPI defaults to streaming uploads but a malicious client could OOM the box. Add a `MAX_UPLOAD_BYTES` check in `app.py` if you expose it past localhost.
- No auth. Trust-the-network for the local POC. Stick the server behind a reverse proxy with a token check before exposing it publicly.
