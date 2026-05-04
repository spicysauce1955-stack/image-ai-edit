# Architecture

The codebase is intentionally small and follows a three-layer adapter pattern. This page is the canonical map of "what calls what."

## Layers

```
┌──────────────────────────────────────────────────────────────────┐
│ scripts/poc.py                       (CLI / entry point)         │
└───────────────────────┬──────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│ src/ai_edit/pipeline/insert.py       (orchestration)             │
│   insert_object(scene, reference, instruction, ...)              │
└──────┬───────────────────────────┬───────────────────────────────┘
       │                           │
       ▼                           ▼
┌──────────────────┐       ┌──────────────────┐
│ Replicate        │       │ Gemini           │
│ (segmentation)   │       │ (multi-image     │
│                  │       │  edit)           │
└──────────────────┘       └──────────────────┘
       │                           │
       ▼                           ▼
┌──────────────────────────────────────────────────────────────────┐
│ src/ai_edit/models/base.py           (interfaces + dataclasses)  │
│   SegmentationModel, EditModel, ImageModel, TextModel            │
│   SegmentationResponse, EditResponse, ImageResponse, ...         │
└──────────────────────────────────────────────────────────────────┘
```

The cardinal rule: **`pipeline/` knows about providers, but providers do not know about each other.** A provider only depends on `models/base.py` and `config.py`. This means swapping one vendor for another (e.g. Gemini → FLUX.1 Kontext) is a single-file change inside `providers/` plus a one-line import swap in `pipeline/insert.py`.

## File map

| Path | Role |
|---|---|
| `scripts/poc.py` | CLI; argparse + I/O wrapper around `insert_object` |
| `src/ai_edit/__init__.py` | Top-level convenience re-exports |
| `src/ai_edit/config.py` | `load_env()`, `get_env()` |
| `src/ai_edit/models/base.py` | All abstract capability classes + response dataclasses |
| `src/ai_edit/models/__init__.py` | Re-exports for ergonomic imports |
| `src/ai_edit/pipeline/insert.py` | The POC orchestrator |
| `src/ai_edit/pipeline/__init__.py` | Re-exports |
| `src/ai_edit/providers/replicate.py` | Grounded-SAM (segmentation) |
| `src/ai_edit/providers/gemini.py` | Gemini 2.5 Flash Image (edit) |
| `src/ai_edit/providers/falai.py` | IC-Light v2 (relighting, M5) |
| `src/ai_edit/providers/minimax.py` | MiniMax text + image (legacy) |
| `src/ai_edit/providers/zhipuai.py` | ZhipuAI text + image (legacy) |
| `src/ai_edit/providers/__init__.py` | Re-exports |

## Capability interfaces

Defined in `models/base.py`:

| Interface | Method | Used by |
|---|---|---|
| `TextModel` | `chat`, `chat_stream` | MiniMax, ZhipuAI |
| `ImageModel` | `generate` | MiniMax, ZhipuAI |
| `SegmentationModel` | `segment(image, prompts)` | Replicate (Grounded-SAM) |
| `EditModel` | `edit(instruction, images)` | Gemini, fal.ai |

A provider may implement multiple interfaces. They do so by attaching capability handlers to themselves in `__init__`:

```python
class Gemini(BaseProvider):
    def __init__(self, ...):
        ...
        self.image = GeminiImage(self)   # implements EditModel
```

Callers then write `gemini.image.edit(...)` rather than `gemini.edit(...)` — keeps the surface area named after the *capability*, not the vendor.

## Data flow for one POC run

1. **CLI** parses flags, loads `.env`, ensures input files exist.
2. **CLI** calls `insert_object(scene_path, reference_path, instruction, segmentation_prompts=...)`.
3. **Pipeline** reads both image files into bytes and infers MIME from extension.
4. **Pipeline** (optional) instantiates `Replicate()` and calls `segmentation.segment(scene_bytes, prompts)`. Masks are kept on the result but **not** fed to Gemini — see [poc-plan.md](./poc-plan.md) for the rationale and the upgrade path.
5. **Pipeline** appends a standard "Image 1 = scene, Image 2 = reference" suffix to the user's instruction.
6. **Pipeline** instantiates `Gemini()` and calls `image.edit(full_instruction, [(scene, mime), (reference, mime)])`.
7. **CLI** writes masks (if any) to `out/masks/` and the composite to `out/composites/`.

## Why this shape

- **One transport (`httpx`) for every provider.** One timeout strategy, one error type to catch, no mixed sync/async footguns. Providers that look idiosyncratic (Gemini's `x-goog-api-key`, fal.ai's `Key <key>`) override `_headers()` and nothing else.
- **`raw` field on every response.** Vendor-specific extras (Replicate's `metrics`, Gemini's `safetyRatings`) are always one attribute access away without polluting the normalized shape.
- **Pipeline does not own provider construction.** `insert_object` accepts injected providers (`replicate=...`, `gemini=...`) so tests can pass fakes without monkeypatching.
- **Masks are dumped, not consumed.** This was a deliberate POC trade-off: it lets us *see* whether Grounded-SAM is identifying the right regions before committing to either of the two upgrade paths (re-paste for occlusion, or vendor swap to a mask-aware editor). See [poc-plan.md](./poc-plan.md) M4 and M5.

## Adding a new capability

If you need something that doesn't fit `TextModel` / `ImageModel` / `SegmentationModel` / `EditModel`:

1. Add a new ABC to `models/base.py` (e.g. `class UpscaleModel(ABC):`).
2. Add a normalized response dataclass alongside it.
3. Implement it on whichever provider exposes it.
4. Re-export both from `models/__init__.py` and `providers/__init__.py`.
5. Wire it into a pipeline (a new module under `pipeline/`).

See [contributing.md](./contributing.md) for the full provider recipe.
