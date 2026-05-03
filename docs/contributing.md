# Contributing

Practical recipes for the most common changes. Read [architecture.md](./architecture.md) first.

## Adding a new provider

Use case: you want to add **FLUX.1 Kontext Pro** as an insertion fallback in case Gemini doesn't preserve the reference fence's texture.

### 1. Create the provider module

`src/ai_edit/providers/bfl.py`:

```python
"""Black Forest Labs provider — FLUX.1 Kontext for reference-conditioned edits."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import BaseProvider, EditModel, EditResponse

BASE_URL = "https://api.bfl.ai"
DEFAULT_KONTEXT_MODEL = "flux-kontext-pro"


class BFLKontext(EditModel):
    def __init__(self, provider: BFL) -> None:
        self._provider = provider

    async def edit(
        self,
        instruction: str,
        images: list[tuple[bytes, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> EditResponse:
        # ... POST + poll + download ...
        return EditResponse(image_bytes=..., mime_type="image/png", raw=...)


class BFL(BaseProvider):
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL) -> None:
        key = api_key or get_env("BFL_API_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.image = BFLKontext(self)

    @property
    def name(self) -> str:
        return "bfl"

    def _headers(self) -> dict[str, str]:
        # BFL uses x-key
        return {"x-key": self.api_key, "Content-Type": "application/json"}
```

### 2. Re-export

`src/ai_edit/providers/__init__.py`:
```python
from .bfl import BFL
__all__ = [..., "BFL"]
```

`src/ai_edit/__init__.py`:
```python
from .providers import ..., BFL
__all__ = [..., "BFL"]
```

### 3. Add the env key

`.env.example`:
```
BFL_API_KEY=
```

### 4. Use it from the pipeline (or expose a flag)

For an A/B swap, parameterize the editor in `insert_object`:

```python
async def insert_object(
    ...,
    editor: EditModel | None = None,  # accept any EditModel
) -> InsertResult:
    ...
    edit = await (editor or Gemini().image).edit(full_instruction, images)
```

Then in the CLI add a `--editor {gemini,bfl}` flag and construct the right provider.

### 5. Add a docstring matching the existing house style

- Module-level docstring covers: what it wraps, why direct httpx, any auth quirks, any response-shape quirks.
- One-line class docstrings on each handler.
- Parameter docs on every public `async def`.
- Inline comments only where the WHY is non-obvious (e.g. "fal.ai uses `Key <key>` instead of `Bearer`").

Look at `providers/gemini.py` for a complete reference implementation.

## Adding a new capability

If the new vendor exposes something none of the existing ABCs cover (e.g. image-to-3D for the AR phase), don't shoehorn it into `EditModel` — add a new ABC.

1. In `models/base.py`:
   ```python
   @dataclass
   class Image3DResponse:
       glb_bytes: bytes = b""
       usdz_bytes: bytes = b""
       raw: dict[str, Any] = field(default_factory=dict)

   class Image3DModel(ABC):
       @abstractmethod
       async def generate(
           self, images: list[tuple[bytes, str]], *, model: str | None = None,
       ) -> Image3DResponse: ...
   ```

2. Re-export from `models/__init__.py`.

3. Implement it on the relevant provider (e.g. `providers/meshy.py`).

4. Build a new pipeline in `pipeline/` rather than overloading `insert.py`. For AR that means `pipeline/ar.py` with something like `build_ar_asset(reference_paths) -> ARAsset`.

## Style conventions

- **Async by default.** Every network call goes through `httpx.AsyncClient`. The CLI uses `asyncio.run`.
- **No SDK imports.** Direct REST keeps the dependency graph small and consistent.
- **Type-hint everything in public signatures.** Use `from __future__ import annotations` at the top of every module so we can use modern syntax (`list[X]`, `X | None`) on Python 3.10.
- **Preserve the `raw` field.** Vendor-specific debugging is the #1 use case.
- **Fail fast on missing env vars.** Constructors call `get_env(..., required=True)` so a missing key is a clear error at startup, not an obscure 401 mid-pipeline.

## Where things live

| Want to … | Edit this |
|---|---|
| Add a vendor | `src/ai_edit/providers/<vendor>.py` + the two `__init__.py`s |
| Add a capability shape | `src/ai_edit/models/base.py` |
| Compose vendors into a workflow | new module under `src/ai_edit/pipeline/` |
| Add a CLI command | new script under `scripts/` |
| Document a design choice | new `docs/<topic>.md`, link from `docs/README.md` |
