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
| `GET` | `/` | Drag-drop upload UI (single static page) |
| `POST` | `/api/insert` | Run the pipeline, return composite as PNG |
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
| `segment` | string | Comma-separated labels for Grounded-SAM (e.g. `"ground,trees,sky"`). Empty = skip segmentation. |
| `relight` | string | IC-Light prompt. Empty = skip relight. Tends to restyle the inserted object — use sparingly. |

Response: a single image (`Content-Type: image/png` or `image/jpeg`) — the composite. Errors from upstream providers are surfaced as `502` with the exception message in the body.

### Example: curl

```bash
curl -sS -o composite.png \
  -X POST http://127.0.0.1:8000/api/insert \
  -F "scene=@yard.png" \
  -F "reference=@fence.jpg" \
  -F "instruction=place this fence along the back edge of the lawn"
```

### Example: Python

```python
import httpx

with open("yard.png", "rb") as scene, open("fence.jpg", "rb") as ref:
    r = httpx.post(
        "http://127.0.0.1:8000/api/insert",
        files={"scene": scene, "reference": ref},
        data={"instruction": "place this fence along the back of the lawn"},
        timeout=120,
    )
r.raise_for_status()
open("composite.png", "wb").write(r.content)
```

## Design notes

- **Stateless.** Nothing is persisted on the server. Uploads land in a `tempfile.TemporaryDirectory` that's cleaned up before the response is sent. Composites are streamed straight back in the response body.
- **Synchronous from the client's POV.** The client gets one HTTP response when the whole pipeline finishes. Long-running jobs (notably IC-Light) hold the connection open. If we ever want true async, the natural pattern is to mirror fal.ai's queue endpoint: return `{job_id, status_url}` and let the client poll.
- **Errors as 502.** Any exception from `insert_object` becomes `502 Bad Gateway` because the API itself is fine — its upstream dependency failed. The exception message is in the response body.
- **No auth.** Trust-the-network for the local POC. Stick the server behind a reverse proxy with a token check before exposing it publicly.

## Caveats

- The static UI at `/` re-implements the CLI's behavior in the browser — it's deliberately one HTML file with inline CSS/JS, no build step. If we want a real frontend (auth, history, multi-tenant), this is the wrong layer to grow it from; build a separate Next.js (or whatever) frontend and call `/api/insert` from there.
- File size isn't capped server-side. FastAPI defaults to streaming uploads but a malicious client could OOM the box. Add a `MAX_UPLOAD_BYTES` check in `app.py` if you expose it past localhost.
