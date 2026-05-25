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
from ..models.base import (
    MIME_GLB,
    BaseProvider,
    EditModel,
    EditResponse,
    Scene3DAsset,
    Scene3DModel,
    Scene3DResponse,
)

BASE_URL = "https://fal.run"
QUEUE_URL = "https://queue.fal.run"
DEFAULT_RELIGHT_MODEL = "fal-ai/iclight-v2"
DEFAULT_INPAINT_MODEL = "fal-ai/flux-kontext-lora/inpaint"
DEFAULT_HUNYUAN3D_MODEL = "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d"
# gpt-image-1.5/edit-image has a known fal-side queue-routing bug
# ("Path /edit-image not found"); the gpt-image-1 (v1) edit-image
# endpoint works through the same SDK path.
DEFAULT_GPTIMAGE_MODEL = "fal-ai/gpt-image-1/edit-image"
DEFAULT_NANO_BANANA_MODEL = "fal-ai/nano-banana-pro/edit"
DEFAULT_FLUX_REF_INPAINT_MODEL = "fal-ai/flux-general/inpainting"
DEFAULT_GPT_IMAGE_2_MODEL = "openai/gpt-image-2/edit"
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


class FalAIGPTImage:
    """fal.ai's hosted ``gpt-image-1/edit-image`` — OpenAI's gpt-image-1
    routed through fal so we charge against ``FAL_KEY`` rather than an
    OpenAI account.

    Why this exists in addition to FLUX-Kontext-LoRA Inpaint
    --------------------------------------------------------
    FLUX-Kontext-LoRA enforces masks well but produces a "generalized"
    version of the reference object — slats and posts smoothed into a
    flat panel — even with strong prompts. gpt-image-1 is a vision-
    grounded transformer that **re-renders** the masked region using
    the reference for appearance and the scene for perspective,
    yielding visibly higher reference fidelity (correct slats, posts,
    shadows, and perspective recession in our fence test).

    Caveat: gpt-image-1's mask is *soft* — the model often regenerates
    pixels beyond the mask boundary too (per the OpenAI developer
    forum). The pipeline always PIL-composites the result back onto
    the original scene using our binary polygon mask, so the polygon
    boundary is enforced deterministically regardless of model
    behaviour.

    SDK vs raw HTTP
    ---------------
    fal's queue endpoint has a known routing bug for sub-pathed models
    like ``gpt-image-1/edit-image`` — submit returns a result URL that
    404s. We use ``fal_client.subscribe`` which works around the bug
    internally. The synchronous edit takes ~30–70 s per call.

    Native fields (per fal's docs):

    - ``image_urls``     : list[str] — scene + reference images.
                           Convention: scene first, refs after.
    - ``mask_image_url`` : str       — PNG, white = inpaint region.
    - ``prompt``         : str       — instruction.
    - ``input_fidelity`` : "low"|"high"
    - ``quality``        : "auto"|"low"|"medium"|"high"
    - ``image_size``     : "auto"|"1024x1024"|"1536x1024"|"1024x1536"
    """

    def __init__(self, provider: FalAI) -> None:
        self._provider = provider

    async def edit(
        self,
        scene: tuple[bytes, str],
        mask: tuple[bytes, str],
        references: list[tuple[bytes, str]],
        prompt: str,
        *,
        model: str | None = None,
        input_fidelity: str = "high",
        quality: str = "high",
        image_size: str = "auto",
        **kwargs: Any,
    ) -> EditResponse:
        """Edit via fal.ai's gpt-image-1 proxy.

        Mask convention: **white = inpaint, black = preserve** (standard
        diffusion semantics). The pipeline rasterizes the polygon
        white-on-black before calling here.
        """
        import fal_client
        import os

        # fal_client reads FAL_KEY from the env at call time; ensure
        # the key from this provider is the one in scope (the helper
        # tolerates the env var being set elsewhere too).
        os.environ.setdefault("FAL_KEY", self._provider.api_key)

        scene_bytes, scene_mime = scene
        mask_bytes, mask_mime = mask

        image_uris = [_data_uri(scene_bytes, scene_mime)]
        for rb, rm in references:
            image_uris.append(_data_uri(rb, rm))

        arguments: dict[str, Any] = {
            "prompt": prompt,
            "image_urls": image_uris,
            "mask_image_url": _data_uri(mask_bytes, mask_mime),
            "input_fidelity": input_fidelity,
            "quality": quality,
            "image_size": image_size,
        }
        arguments.update(kwargs)

        # fal_client.subscribe is sync; run on a worker thread so we
        # don't block the event loop.
        result = await asyncio.to_thread(
            fal_client.subscribe,
            model or DEFAULT_GPTIMAGE_MODEL,
            arguments=arguments,
            with_logs=False,
        )

        url = _first_image_url(result)
        return EditResponse(
            image_bytes=await _download(url),
            mime_type="image/png",
            raw=result,
        )


class FalAIGPTImage2:
    """OpenAI gpt-image-2 (released April 21, 2026) hosted on fal.

    fal endpoint: ``openai/gpt-image-2/edit`` — proxies the model
    against ``FAL_KEY`` so we don't need OpenAI billing unlocked.

    Why it's the breakthrough we've been waiting for:

    OpenAI explicitly improved gpt-image-2's instruction following
    over gpt-image-1: "stronger editing, better layouts, improved
    text rendering, more reliable instruction-following" (OpenAI's
    own release post). The "more reliable instruction-following" is
    the architectural fix for the semantic-prior trap that made
    every prior gpt-image-1 / Nano Banana call relocate inserted
    objects to "where they normally belong" in the scene.

    Native fields (per fal docs):

    - ``image_urls``     : list[str] — scene + reference (scene first)
    - ``mask_url``       : str       — PNG mask, white = inpaint region
    - ``prompt``         : str
    - ``quality``        : "auto"|"low"|"medium"|"high" (default "high")
    - ``image_size``     : "auto" or specific dims

    Latency: ~200 s at quality=high (the model "thinks" before rendering).
    Cost: ~$0.08–0.20 per call depending on quality/size.
    """

    def __init__(self, provider: FalAI) -> None:
        self._provider = provider

    async def edit(
        self,
        scene: tuple[bytes, str],
        mask: tuple[bytes, str],
        references: list[tuple[bytes, str]],
        prompt: str,
        *,
        model: str | None = None,
        quality: str = "high",
        image_size: str = "auto",
        **kwargs: Any,
    ) -> EditResponse:
        """Mask-bound, reference-conditioned edit via gpt-image-2 on fal."""
        import fal_client
        import os

        os.environ.setdefault("FAL_KEY", self._provider.api_key)

        sb, sm = scene
        mb, mm = mask

        image_uris = [_data_uri(sb, sm)]
        for rb, rm in references:
            image_uris.append(_data_uri(rb, rm))

        arguments: dict[str, Any] = {
            "prompt": prompt,
            "image_urls": image_uris,
            "mask_url": _data_uri(mb, mm),
            "quality": quality,
            "image_size": image_size,
        }
        arguments.update(kwargs)

        result = await asyncio.to_thread(
            fal_client.subscribe,
            model or DEFAULT_GPT_IMAGE_2_MODEL,
            arguments=arguments,
            with_logs=False,
        )
        url = _first_image_url(result)
        return EditResponse(
            image_bytes=await _download(url),
            mime_type="image/png",
            raw=result,
        )


class FalAIFluxRefInpaint:
    """fal-ai/flux-general/inpainting with native reference conditioning.

    The single hosted endpoint that takes ALL FOUR inputs natively:
      - ``image_url``           : the scene
      - ``mask_url``            : binary polygon mask
      - ``reference_image_url`` : the object reference
      - ``prompt``              : text instruction

    Plus ``reference_strength`` (default 0.65) which controls how
    strongly the reference image conditions the inpainted region.
    Empirically (May 2026 sweep saved at docs/results/23-*) this
    endpoint produced 0.0% strong outside-mask drift on the
    yard+fence variant-B test — better than every other engine — and
    delivered visible reference-conditioned fence rendering inside the
    polygon with steps=50, guidance_scale=5.0.

    The mask is treated as a hard alpha constraint at the provider
    level (FLUX inpainting semantics), so we never have to fight the
    semantic-prior trap that gpt-image-1 / Nano Banana suffer from.
    """

    def __init__(self, provider: FalAI) -> None:
        self._provider = provider

    async def edit(
        self,
        scene: tuple[bytes, str],
        mask: tuple[bytes, str],
        reference: tuple[bytes, str],
        prompt: str,
        *,
        model: str | None = None,
        num_inference_steps: int = 50,
        guidance_scale: float = 5.0,
        reference_strength: float = 0.65,
        **kwargs: Any,
    ) -> EditResponse:
        """Run mask-bound, reference-conditioned inpainting via fal."""
        import fal_client
        import os

        os.environ.setdefault("FAL_KEY", self._provider.api_key)

        sb, sm = scene
        mb, mm = mask
        rb, rm = reference

        arguments: dict[str, Any] = {
            "prompt": prompt,
            "image_url": _data_uri(sb, sm),
            "mask_url": _data_uri(mb, mm),
            "reference_image_url": _data_uri(rb, rm),
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "reference_strength": reference_strength,
        }
        arguments.update(kwargs)

        result = await asyncio.to_thread(
            fal_client.subscribe,
            model or DEFAULT_FLUX_REF_INPAINT_MODEL,
            arguments=arguments,
            with_logs=False,
        )
        url = _first_image_url(result)
        return EditResponse(
            image_bytes=await _download(url),
            mime_type="image/png",
            raw=result,
        )


class FalAINanoBanana:
    """Nano Banana family on fal.ai (Google's Gemini-3 image-edit models).

    Endpoints:
      - fal-ai/nano-banana-pro/edit  — Gemini 3 Pro Image (most capable)
      - fal-ai/nano-banana-2/edit    — Gemini 3.1 Flash Image
      - fal-ai/nano-banana/edit      — Gemini 2.5 Flash Image (original)

    These are mask-LESS edit endpoints: ``image_urls`` (list, scene
    first then references) + ``prompt``. The pipeline's ``gemini_crop``
    mask engine drives spatial control by cropping the polygon's
    bounding-box region BEFORE the call (so the model can't relocate
    to "where this object normally goes" — those locations aren't in
    the cropped view) and reassembling the edited crop into the full
    scene afterwards.
    """

    def __init__(self, provider: FalAI) -> None:
        self._provider = provider

    async def edit(
        self,
        scene: tuple[bytes, str],
        references: list[tuple[bytes, str]],
        prompt: str,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> EditResponse:
        """Mask-LESS Gemini-family edit. ``image_urls = [scene, *refs]``."""
        import fal_client
        import os

        os.environ.setdefault("FAL_KEY", self._provider.api_key)

        sb, sm = scene
        image_uris = [_data_uri(sb, sm)]
        for rb, rm in references:
            image_uris.append(_data_uri(rb, rm))

        arguments: dict[str, Any] = {"prompt": prompt, "image_urls": image_uris}
        arguments.update(kwargs)

        result = await asyncio.to_thread(
            fal_client.subscribe,
            model or DEFAULT_NANO_BANANA_MODEL,
            arguments=arguments,
            with_logs=False,
        )
        url = _first_image_url(result)
        return EditResponse(
            image_bytes=await _download(url),
            mime_type="image/png",
            raw=result,
        )


# Hunyuan3D 3.1 takes multi-view input as NAMED SLOTS, not an array.
# The ordered `references` list maps positionally onto the slots below.
# NOTE: the required primary (front) view is ``input_image_url`` — NOT
# ``front_image_url`` (verified against the live 422 schema, 2026-05-25).
# v3.1 also accepts top/bottom/diagonal slots
# (``top_image_url``, ``bottom_image_url``, ``left_front_image_url``,
# ``right_front_image_url``); pass those by name via kwargs. See
# docs/stack-decision.md and research/image-to-3d/synthesis.md.
_HUNYUAN_VIEW_SLOTS = (
    "input_image_url",   # references[0] — required (front view)
    "back_image_url",    # references[1]
    "left_image_url",    # references[2]
    "right_image_url",   # references[3]
)


def _first_model_url(data: dict[str, Any]) -> str:
    """Return the GLB download URL from a Hunyuan3D result, or raise.

    The result puts the mesh at ``model_glb.url`` and also mirrors it
    under ``model_urls.glb.url``; we check both.
    """
    glb = data.get("model_glb")
    if isinstance(glb, dict) and glb.get("url"):
        return glb["url"]
    glb2 = (data.get("model_urls") or {}).get("glb")
    if isinstance(glb2, dict) and glb2.get("url"):
        return glb2["url"]
    raise RuntimeError(f"fal.ai returned no GLB model. Raw: {data}")


class FalAIMultiImageTo3D(Scene3DModel):
    """Hunyuan3D 3.1 Pro image-to-3D on fal.ai — multi-view → GLB.

    Implements the :class:`Scene3DModel` capability. ``references`` is
    an ordered list of ``(bytes, mime)`` photos of ONE object, mapped
    positionally onto Hunyuan3D's named view slots (front, back, left,
    right). The first (front) image is **required**. References beyond
    the four cardinals are ignored unless their slot is passed
    explicitly via ``kwargs`` (e.g. ``top_image_url=...``).

    ``prompt`` is accepted for interface conformance but **not sent** —
    the image-to-3d endpoint is image-driven and exposes no text
    prompt (text conditioning lives on the separate text-to-3d
    endpoint).

    Cost (May 2026): ~$0.375 base; +$0.15 each for ``enable_pbr``,
    multi-view (>1 image), and custom ``face_count``. Forward those via
    kwargs. First cut returns GLB only (USDZ deferred to a
    Format3DConverter pass).
    """

    def __init__(self, provider: FalAI) -> None:
        self._provider = provider

    async def generate(
        self,
        prompt: str,
        references: list[tuple[bytes, str]] | None = None,
        *,
        model: str | None = None,
        target_format: str = "glb",
        **kwargs: Any,
    ) -> Scene3DResponse:
        """Generate a GLB from one or more angled photos of an object."""
        import os

        import fal_client

        if not references:
            raise ValueError(
                "FalAIMultiImageTo3D.generate requires at least one reference "
                "image (the front view)."
            )

        os.environ.setdefault("FAL_KEY", self._provider.api_key)

        arguments: dict[str, Any] = {}
        for (data, mime), slot in zip(references, _HUNYUAN_VIEW_SLOTS):
            arguments[slot] = _data_uri(data, mime)
        # generate_type / enable_pbr / face_count / extra named view
        # slots pass straight through.
        arguments.update(kwargs)

        result = await asyncio.to_thread(
            fal_client.subscribe,
            model or DEFAULT_HUNYUAN3D_MODEL,
            arguments=arguments,
            with_logs=False,
        )
        glb_bytes = await _download(_first_model_url(result))
        return Scene3DResponse(
            assets=[
                Scene3DAsset(
                    data=glb_bytes,
                    mime_type=MIME_GLB,
                    extension=".glb",
                    raw=result,
                )
            ],
            raw=result,
        )


class FalAI(BaseProvider):
    """fal.ai REST client. Exposes IC-Light, FLUX-Kontext-LoRA inpaint, gpt-image-1, Nano Banana, and Hunyuan3D image-to-3D."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("FAL_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.relight = FalAIRelight(self)
        self.inpaint = FalAIInpaintRef(self)
        self.gpt_image = FalAIGPTImage(self)
        self.gpt_image_2 = FalAIGPTImage2(self)
        self.nano_banana = FalAINanoBanana(self)
        self.flux_ref_inpaint = FalAIFluxRefInpaint(self)
        self.multi_image_3d = FalAIMultiImageTo3D(self)

    @property
    def name(self) -> str:
        return "falai"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }
