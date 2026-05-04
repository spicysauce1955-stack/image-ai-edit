"""fal.ai provider — IC-Light v2 relighting and FLUX-Kontext-LoRA inpaint.

Two handlers attached to the same provider:

- :class:`FalAIRelight` — IC-Light v2 (single-image relight, optional
  post-processing pass).
- :class:`FalAIInpaintRef` — FLUX-Kontext-LoRA Inpaint (mask-bound
  reference-conditioned inpainting). The strict-placement primitive
  the rest of the pipeline routes mask-mode requests through.

Auth quirk
----------
fal.ai uses ``Authorization: Key <api_key>`` rather than the more
common ``Bearer`` scheme — that's why this provider overrides
:meth:`BaseProvider._headers`.

Sync vs queue endpoint
----------------------
fal exposes two endpoints for every model:

- ``https://fal.run/<model>`` — synchronous. Hits a hard ~180 s
  gateway timeout, which is *not* enough for the cold starts on the
  models we use.
- ``https://queue.fal.run/<model>`` — submit + poll. We use this for
  every call below; the shared :func:`_run_queue` helper handles
  submit, poll-to-completion, fetch-result, and download.
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
DEFAULT_INPAINT_MODEL = "fal-ai/flux-kontext-lora/inpaint"
POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 600.0


def _data_uri(image_bytes: bytes, mime_type: str) -> str:
    """Encode local image bytes as a ``data:`` URI for inline upload."""
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


async def _run_queue(
    provider: FalAI,
    model_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Submit a payload to fal.ai's queue endpoint, poll, return the result.

    Submit returns ``{status_url, response_url}``. We poll
    ``status_url`` until ``COMPLETED`` then fetch ``response_url``.
    Times out generously at :data:`POLL_TIMEOUT_S` to absorb cold
    starts on big models.

    The caller is responsible for picking out whatever fields it
    cares about from the returned JSON.
    """
    submit_url = f"{QUEUE_URL}/{model_id}"
    async with httpx.AsyncClient(timeout=60) as client:
        submit = await client.post(
            submit_url, headers=provider._headers(), json=payload
        )
        submit.raise_for_status()
        sub = submit.json()

        status_url = sub.get("status_url")
        response_url = sub.get("response_url")
        if not status_url or not response_url:
            raise RuntimeError(f"fal.ai queue submit returned no URLs: {sub}")

        elapsed = 0.0
        while True:
            if elapsed >= POLL_TIMEOUT_S:
                raise TimeoutError(
                    f"fal.ai prediction timed out after {POLL_TIMEOUT_S}s"
                )
            await asyncio.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            poll = await client.get(status_url, headers=provider._headers())
            poll.raise_for_status()
            status = poll.json().get("status")
            if status == "COMPLETED":
                break
            if status in ("FAILED", "CANCELED", "ERROR"):
                raise RuntimeError(f"fal.ai prediction {status}: {poll.json()}")

        final = await client.get(response_url, headers=provider._headers())
        final.raise_for_status()
        return final.json()


def _first_image_url(data: dict[str, Any]) -> str:
    """Return the first image URL from a fal.ai response, or raise."""
    images_out = data.get("images") or []
    if images_out:
        url = images_out[0].get("url")
        if url:
            return url
    if "image" in data:
        url = data["image"].get("url")
        if url:
            return url
    raise RuntimeError(f"fal.ai returned no image. Raw: {data}")


async def _download(url: str, *, retries: int = 5) -> bytes:
    """Download a URL with retries on transient 5xx and network errors.

    fal.ai's CDN occasionally serves a 502 or stalls in the few
    seconds after a job completes (the asset is propagating). We retry
    on 5xx, ReadTimeout, and ConnectError; everything else propagates.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt == retries - 1:
                raise
            last_exc = exc
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            if attempt == retries - 1:
                raise
            last_exc = exc
        await asyncio.sleep(2.0 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


class FalAIRelight(EditModel):
    """IC-Light v2 relighting client (queue-based).

    Implements :class:`EditModel` so the pipeline can chain it after
    Gemini without a special-case branch — pass the composite as the
    single input image and the desired lighting description as the
    ``instruction``.
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

        data = await _run_queue(self._provider, model or DEFAULT_RELIGHT_MODEL, payload)
        url = _first_image_url(data)
        return EditResponse(
            image_bytes=await _download(url), mime_type="image/png", raw=data
        )


class FalAIInpaintRef:
    """FLUX-Kontext-LoRA mask-bound reference-conditioned inpainting.

    Native fields on ``fal-ai/flux-kontext-lora/inpaint``:

    - ``image_url``           — the scene
    - ``mask_url``            — binary PNG: white = fill, black = preserve
    - ``reference_image_url`` — the object to insert
    - ``prompt``              — text describing the edit

    The endpoint enforces the mask as a hard alpha constraint and
    composites the reference's appearance into the white region. Pass
    ``guidance_scale``, ``num_inference_steps``, ``strength`` etc. via
    ``**kwargs`` to tune adherence vs. creativity.

    Not implementing :class:`EditModel` because that interface assumes
    an arbitrary list of images keyed by position; this endpoint has
    four named slots and we want them spelled out in the call site.
    """

    def __init__(self, provider: FalAI) -> None:
        self._provider = provider

    async def inpaint(
        self,
        scene: tuple[bytes, str],
        mask: tuple[bytes, str],
        reference: tuple[bytes, str],
        prompt: str,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> EditResponse:
        """Run reference-conditioned mask-bound inpainting.

        Parameters
        ----------
        scene, mask, reference:
            ``(bytes, mime_type)`` tuples. The mask must match the
            scene's pixel dimensions. White pixels in the mask = fill;
            black = preserve identical to scene.
        prompt:
            What to put inside the mask. Reference image carries the
            object's appearance; the prompt is supplemental.
        model:
            Override the default endpoint id.
        **kwargs:
            Forwarded into the request body. Useful values:

            - ``num_inference_steps`` (default 30)
            - ``guidance_scale`` (default ~3.5)
            - ``strength`` (how much to deviate from the reference)
            - ``acceleration`` ("none" / "regular" / "high")
        """
        scene_bytes, scene_mime = scene
        mask_bytes, mask_mime = mask
        ref_bytes, ref_mime = reference

        payload: dict[str, Any] = {
            "image_url": _data_uri(scene_bytes, scene_mime),
            "mask_url": _data_uri(mask_bytes, mask_mime),
            "reference_image_url": _data_uri(ref_bytes, ref_mime),
            "prompt": prompt,
        }
        payload.update(kwargs)

        data = await _run_queue(self._provider, model or DEFAULT_INPAINT_MODEL, payload)
        url = _first_image_url(data)
        return EditResponse(
            image_bytes=await _download(url), mime_type="image/png", raw=data
        )


class FalAI(BaseProvider):
    """fal.ai REST client. Exposes IC-Light + FLUX-Kontext-LoRA inpaint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("FAL_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.relight = FalAIRelight(self)
        self.inpaint = FalAIInpaintRef(self)

    @property
    def name(self) -> str:
        return "falai"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }
