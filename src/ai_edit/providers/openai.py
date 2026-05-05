"""OpenAI provider — gpt-image-1 image-edit with native mask + reference list.

Why this provider exists
------------------------
FLUX-Kontext-LoRA Inpaint on fal.ai honors the mask boundary but, even
with reference conditioning, ends up producing a "generalized" version
of the reference object — slats and posts smoothed into a flat panel.
Pre-pasting the reference and refining at low strength preserves the
reference's pixels but reads as "pasted, not inserted" because the
diffusion pass can't re-render the reference in the scene's perspective.

OpenAI's ``gpt-image-1`` image-edit endpoint takes:

- ``image``  — the scene
- ``mask``   — a PNG whose **alpha channel** marks the inpaint region:
               TRANSPARENT pixels are inpainted, OPAQUE pixels are
               preserved (this is the OpenAI semantics, opposite of
               most diffusion APIs that use white = fill).
- ``image[]`` — a list of additional reference images that the model
                can attend to.
- ``prompt`` — text instructions.

Because gpt-image-1 is a vision-grounded transformer rather than a
pixel-space diffusion inpainter, it tends to *re-render* the reference
in the masked region using the scene's perspective and lighting,
rather than copy-and-blend pixels. That's the property we want.

Auth
----
Standard OpenAI Bearer token. The :data:`OPENAI_API_KEY` env var must
be a real OpenAI key (``sk-proj-...``), NOT a key for an
OpenAI-compatible third-party endpoint (BigModel/Zhipu/etc.).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_env
from ..models.base import BaseProvider, EditResponse

BASE_URL = "https://api.openai.com"
DEFAULT_MODEL = "gpt-image-1"
EDIT_TIMEOUT_S = 240.0


class OpenAIImageEdit:
    """gpt-image-1 image-edit handler.

    Not implementing the generic :class:`EditModel` interface because
    gpt-image-1 has named slots (``image`` vs ``image[]`` vs ``mask``)
    that don't map cleanly onto a positional list. The pipeline calls
    this directly when in mask mode.
    """

    def __init__(self, provider: OpenAI) -> None:
        self._provider = provider

    async def edit(
        self,
        scene: tuple[bytes, str],
        mask: tuple[bytes, str],
        references: list[tuple[bytes, str]],
        prompt: str,
        *,
        model: str | None = None,
        size: str = "auto",
        quality: str = "high",
        n: int = 1,
        **kwargs: Any,
    ) -> EditResponse:
        """Run a mask-bound, reference-conditioned image edit.

        Parameters
        ----------
        scene:
            ``(bytes, mime_type)`` — the photo we're editing into.
        mask:
            ``(bytes, mime_type)`` — a PNG with an alpha channel.
            **Transparent** pixels mark the region to inpaint (OpenAI
            semantics). The mask must match the scene's dimensions.
        references:
            List of ``(bytes, mime_type)`` reference images. They go
            into the multipart form as ``image[]`` and the model
            attends to them as appearance references.
        prompt:
            Text instruction. Even with strong references, gpt-image-1
            benefits from explicit guidance ("place the fence inside
            the masked region, preserve its design, match perspective…").
        model:
            Override the default model identifier.
        size, quality, n:
            Standard OpenAI Images-Edit knobs. ``size="auto"`` lets the
            model match the input scene's dimensions.
        **kwargs:
            Additional form fields forwarded as-is.

        Notes
        -----
        gpt-image-1 returns base64-encoded image bytes in JSON
        (response_format is implicitly base64 — there is no URL form
        for this model). We decode and return the bytes.
        """
        scene_bytes, scene_mime = scene
        mask_bytes, mask_mime = mask

        # gpt-image-1 multipart: every input image goes into the
        # repeated ``image[]`` field. The FIRST element is the canvas
        # (the scene we're editing), the rest are reference images.
        # ``mask`` is its own field and applies to the canvas.
        # Mixing ``image`` (singular) and ``image[]`` (list) in the
        # same request is rejected with HTTP 400.
        files: list[tuple[str, tuple[str, bytes, str]]] = [
            ("image[]", ("scene.png", scene_bytes, scene_mime)),
        ]
        for i, (rb, rm) in enumerate(references):
            files.append(("image[]", (f"ref-{i}.png", rb, rm)))
        files.append(("mask", ("mask.png", mask_bytes, mask_mime)))

        data: dict[str, Any] = {
            "model": model or DEFAULT_MODEL,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": str(n),
        }
        for k, v in kwargs.items():
            data[k] = str(v)

        url = f"{self._provider.base_url}/v1/images/edits"
        headers = {"Authorization": f"Bearer {self._provider.api_key}"}

        async with httpx.AsyncClient(timeout=EDIT_TIMEOUT_S) as client:
            resp = await client.post(url, headers=headers, data=data, files=files)
            resp.raise_for_status()
            payload = resp.json()

        items = payload.get("data") or []
        if not items:
            raise RuntimeError(f"OpenAI returned no images. Raw: {payload}")
        item = items[0]
        b64 = item.get("b64_json")
        if not b64:
            # gpt-image-1 may also return a URL in some edge cases.
            url_field = item.get("url")
            if url_field:
                async with httpx.AsyncClient(timeout=60) as c:
                    img = await c.get(url_field)
                    img.raise_for_status()
                    return EditResponse(
                        image_bytes=img.content,
                        mime_type="image/png",
                        raw=payload,
                    )
            raise RuntimeError(f"OpenAI response had no b64_json or url. Raw: {payload}")

        import base64
        return EditResponse(
            image_bytes=base64.b64decode(b64),
            mime_type="image/png",
            raw=payload,
        )


class OpenAI(BaseProvider):
    """Real OpenAI REST client (not BigModel/Zhipu/other compat shims).

    Currently exposes ``image_edit`` only. The provider deliberately
    reads ``OPENAI_API_KEY`` and *requires* it to be a real OpenAI
    key — passing a BigModel-style key here will fail at the API.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("OPENAI_API_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.image_edit = OpenAIImageEdit(self)

    @property
    def name(self) -> str:
        return "openai"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}
