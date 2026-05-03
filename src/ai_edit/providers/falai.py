"""fal.ai provider — IC-Light v2 relighting.

Used (or *will be* used, once M5 of the POC plan kicks in) as a
post-processing step that relights a finished composite to match the
scene's sun direction. Treat it as optional: the pipeline is correct
without it, just less convincing on lighting-sensitive scenes.

Auth quirk
----------
fal.ai uses ``Authorization: Key <api_key>`` rather than the more common
``Bearer`` scheme — that's why this provider overrides
:meth:`BaseProvider._headers`.

Sync vs queue
-------------
fal exposes two endpoints for every model:

- ``https://fal.run/<model>`` — synchronous. Blocks until the model
  finishes. Fine for IC-Light because it returns in a few seconds.
- ``https://queue.fal.run/<model>`` — async with polling. Needed for
  long jobs (e.g. video).

We use the sync endpoint here since IC-Light is fast.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import BaseProvider, EditModel, EditResponse

BASE_URL = "https://fal.run"
QUEUE_URL = "https://queue.fal.run"
DEFAULT_RELIGHT_MODEL = "fal-ai/iclight-v2"
POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 180.0


def _data_uri(image_bytes: bytes, mime_type: str) -> str:
    """Encode a local image as a ``data:`` URI for inline upload."""
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


class FalAIRelight(EditModel):
    """IC-Light v2 relighting client.

    Implements :class:`EditModel` so the pipeline can chain it after
    Gemini without a special-case branch — pass the Gemini composite
    as the single input image and the desired lighting description as
    the ``instruction``.

    The first image in ``images`` is used; any others are ignored
    because IC-Light is single-image. We chose to keep the
    :class:`EditModel` shape rather than a dedicated ``relight()`` method
    so the pipeline can swap relighters without touching its call site.
    """

    def __init__(self, provider: FalAI) -> None:
        self._provider = provider

    async def edit(
        self,
        instruction: str,
        images: list[tuple[bytes, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> EditResponse:
        """Relight ``images[0]`` using ``instruction`` as the prompt."""
        if not images:
            raise ValueError("FalAIRelight.edit requires at least one input image.")
        image_bytes, mime = images[0]

        payload: dict[str, Any] = {
            "image_url": _data_uri(image_bytes, mime),
            "prompt": instruction,
        }
        payload.update(kwargs)

        target = f"{BASE_URL}/{model or DEFAULT_RELIGHT_MODEL}"

        async with httpx.AsyncClient(timeout=POLL_TIMEOUT_S) as client:
            resp = await client.post(
                target, headers=self._provider._headers(), json=payload
            )
            resp.raise_for_status()
            data = resp.json()

            # fal.ai response shape varies by model: most use
            # ``images[].url`` but a few wrap a single result in
            # ``image.url``. Try both before giving up.
            url = None
            images_out = data.get("images") or []
            if images_out:
                url = images_out[0].get("url")
            if not url and "image" in data:
                url = data["image"].get("url")
            if not url:
                raise RuntimeError(f"fal.ai returned no image. Raw: {data}")

            img_resp = await client.get(url)
            img_resp.raise_for_status()

        return EditResponse(
            image_bytes=img_resp.content,
            mime_type="image/png",
            raw=data,
        )


class FalAI(BaseProvider):
    """fal.ai REST client. Currently exposes IC-Light relighting only.

    Add more models (e.g. FLUX.1 Kontext as an insertion fallback,
    Hunyuan3D for the AR phase) by attaching additional handlers in
    ``__init__``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("FAL_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.relight = FalAIRelight(self)

    @property
    def name(self) -> str:
        return "falai"

    def _headers(self) -> dict[str, str]:
        # Override: fal.ai uses ``Authorization: Key <key>`` instead of
        # the ``Bearer`` scheme assumed by BaseProvider.
        return {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }
