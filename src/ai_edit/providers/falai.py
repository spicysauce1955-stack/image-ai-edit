"""fal.ai provider — IC-Light v2 relighting.

Used as a post-processing step that relights a finished composite to
match the scene's sun direction. Treat it as optional: the pipeline is
correct without it, just less convincing on lighting-sensitive scenes.

Auth quirk
----------
fal.ai uses ``Authorization: Key <api_key>`` rather than the more common
``Bearer`` scheme — that's why this provider overrides
:meth:`BaseProvider._headers`.

Sync vs queue endpoint
----------------------
fal exposes two endpoints for every model:

- ``https://fal.run/<model>`` — synchronous. Blocks until the model
  finishes. Hits a hard ~180 s gateway timeout, which is *not* enough
  for IC-Light v2 cold starts.
- ``https://queue.fal.run/<model>`` — submit + poll. Returns immediately
  with a status URL; we poll until ``COMPLETED`` and then fetch the
  result via ``response_url``.

We use the **queue** endpoint here because IC-Light v2 routinely runs
30–90 s warm and several minutes cold, and the sync endpoint cancels
us before that finishes.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import BaseProvider, EditModel, EditResponse

BASE_URL = "https://fal.run"
QUEUE_URL = "https://queue.fal.run"
DEFAULT_RELIGHT_MODEL = "fal-ai/iclight-v2"
POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 600.0


def _data_uri(image_bytes: bytes, mime_type: str) -> str:
    """Encode a local image as a ``data:`` URI for inline upload."""
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


class FalAIRelight(EditModel):
    """IC-Light v2 relighting client (queue-based).

    Implements :class:`EditModel` so the pipeline can chain it after
    Gemini without a special-case branch — pass the Gemini composite
    as the single input image and the desired lighting description as
    the ``instruction``.

    The first image in ``images`` is used; any others are ignored
    because IC-Light is single-image. We chose to keep the
    :class:`EditModel` shape rather than a dedicated ``relight()``
    method so the pipeline can swap relighters without touching its
    call site.
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
        """Relight ``images[0]`` using ``instruction`` as the prompt.

        Submits to the queue endpoint, polls until the request is
        ``COMPLETED``, then fetches the response and downloads the
        first image. Polling timeout is generous (10 min) to absorb
        cold starts.
        """
        if not images:
            raise ValueError("FalAIRelight.edit requires at least one input image.")
        image_bytes, mime = images[0]

        payload: dict[str, Any] = {
            "image_url": _data_uri(image_bytes, mime),
            "prompt": instruction,
        }
        payload.update(kwargs)

        model_id = model or DEFAULT_RELIGHT_MODEL
        submit_url = f"{QUEUE_URL}/{model_id}"

        async with httpx.AsyncClient(timeout=60) as client:
            # 1. Submit — returns immediately with status + response URLs.
            submit = await client.post(
                submit_url, headers=self._provider._headers(), json=payload
            )
            submit.raise_for_status()
            sub = submit.json()

            status_url = sub.get("status_url")
            response_url = sub.get("response_url")
            if not status_url or not response_url:
                raise RuntimeError(f"fal.ai queue submit returned no URLs: {sub}")

            # 2. Poll. fal returns IN_QUEUE / IN_PROGRESS / COMPLETED.
            elapsed = 0.0
            while True:
                if elapsed >= POLL_TIMEOUT_S:
                    raise TimeoutError(
                        f"fal.ai prediction timed out after {POLL_TIMEOUT_S}s"
                    )
                await asyncio.sleep(POLL_INTERVAL_S)
                elapsed += POLL_INTERVAL_S
                poll = await client.get(status_url, headers=self._provider._headers())
                poll.raise_for_status()
                status = poll.json().get("status")
                if status == "COMPLETED":
                    break
                if status in ("FAILED", "CANCELED", "ERROR"):
                    raise RuntimeError(f"fal.ai prediction {status}: {poll.json()}")

            # 3. Fetch the actual result.
            final = await client.get(response_url, headers=self._provider._headers())
            final.raise_for_status()
            data = final.json()

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
