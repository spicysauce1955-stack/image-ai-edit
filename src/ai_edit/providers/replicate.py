"""Replicate provider — open-vocabulary segmentation via Grounded-SAM.

Why direct ``httpx`` instead of the official ``replicate`` SDK
--------------------------------------------------------------
Three reasons:

1. The whole codebase already speaks ``httpx`` (see ``minimax.py`` /
   ``zhipuai.py``), so adding an SDK would split the patterns.
2. Replicate's REST surface is small enough that polling + downloading
   one URL is shorter than learning the SDK's iterator semantics.
3. We avoid an extra runtime dependency that would ship transitively
   into anything that imports :mod:`ai_edit`.

How Grounded-SAM is invoked
---------------------------
The ``schananas/grounded_sam`` model takes a single ``image`` (URL or
data URI) and a comma-separated ``mask_prompt`` string. We encode the
caller's local image as a ``data:`` URI so they never have to upload to
S3 first. The model returns one or more PNG mask URLs which we fetch
and hand back as :class:`SegmentationMask` objects — labelled in the
order the prompts came in, with a trailing ``"combined"`` mask if the
model emits one (Grounded-SAM's behavior here is mildly unstable across
versions, so the zip is intentionally tolerant of length mismatches).

Polling
-------
Replicate predictions are async — POST creates a job, then we poll the
``urls.get`` endpoint until status leaves ``starting``/``processing``.
A 120 s ceiling keeps a hung job from blocking the CLI forever.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from ..config import get_env
from ..models.base import (
    BaseProvider,
    SegmentationMask,
    SegmentationModel,
    SegmentationResponse,
)

BASE_URL = "https://api.replicate.com"
GROUNDED_SAM_MODEL = "schananas/grounded_sam"
POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 120.0


def _data_uri(image_bytes: bytes, mime_type: str) -> str:
    """Encode a local image as a ``data:`` URI for inline upload.

    Avoids the round-trip of pre-uploading to object storage just to get
    a URL Replicate will accept.
    """
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


class ReplicateGroundedSAM(SegmentationModel):
    """Grounded-SAM client.

    Combines Grounding DINO (text → bounding box) with SAM (box → mask)
    to produce open-vocabulary segmentation. Cheaper and faster than
    SAM 2 alone for our use case because we drive it from text labels
    rather than user-clicked points.
    """

    def __init__(self, provider: Replicate) -> None:
        self._provider = provider

    async def segment(
        self,
        image: bytes,
        prompts: list[str],
        *,
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> SegmentationResponse:
        """Run segmentation for one or more text labels.

        Parameters
        ----------
        image:
            Raw bytes of the source image (JPEG/PNG).
        prompts:
            One label per region of interest, e.g. ``["ground", "trees"]``.
            Grounded-SAM concatenates them comma-separated under the
            hood and emits one mask per matched label.
        mime_type:
            MIME type of ``image`` for the data URI envelope.
        **kwargs:
            Forwarded into the model ``input`` dict — useful for
            ``adjustment_factor`` or ``negative_mask_prompt``.
        """
        image_uri = _data_uri(image, mime_type)
        prompt_str = ",".join(p.strip() for p in prompts)

        payload: dict[str, Any] = {
            "input": {
                "image": image_uri,
                "mask_prompt": prompt_str,
                # Negative prompt subtracts regions; default empty to
                # keep behavior predictable for the POC.
                "negative_mask_prompt": kwargs.pop("negative_mask_prompt", ""),
                # 0 = use the model's default mask threshold.
                "adjustment_factor": kwargs.pop("adjustment_factor", 0),
            }
        }
        payload["input"].update(kwargs)

        async with httpx.AsyncClient(timeout=POLL_TIMEOUT_S) as client:
            create = await client.post(
                f"{self._provider.base_url}/v1/models/{GROUNDED_SAM_MODEL}/predictions",
                headers=self._provider._headers(),
                json=payload,
            )
            create.raise_for_status()
            prediction = create.json()

            prediction = await self._wait(client, prediction)

            output = prediction.get("output") or []
            mask_urls = output if isinstance(output, list) else [output]

            # Replicate may return N masks for N prompts plus a combined
            # union mask. zip() naturally truncates to the shorter list,
            # which is the behavior we want regardless of which side
            # comes up short.
            masks: list[SegmentationMask] = []
            for label, url in zip(prompts + ["combined"], mask_urls):
                if not url:
                    continue
                resp = await client.get(url)
                resp.raise_for_status()
                masks.append(
                    SegmentationMask(
                        label=label,
                        image_bytes=resp.content,
                        mime_type="image/png",
                    )
                )

        return SegmentationResponse(masks=masks, raw=prediction)

    async def _wait(
        self, client: httpx.AsyncClient, prediction: dict[str, Any]
    ) -> dict[str, Any]:
        """Poll a Replicate prediction to completion.

        Replicate returns a job descriptor on creation; the actual
        output URLs only show up once ``status == "succeeded"``. We poll
        the ``urls.get`` endpoint at ``POLL_INTERVAL_S`` and bail with a
        :class:`TimeoutError` after ``POLL_TIMEOUT_S`` to keep the CLI
        responsive when something goes sideways upstream.
        """
        get_url = prediction.get("urls", {}).get("get")
        if not get_url:
            return prediction
        elapsed = 0.0
        while prediction.get("status") in ("starting", "processing"):
            if elapsed >= POLL_TIMEOUT_S:
                raise TimeoutError(
                    f"Replicate prediction timed out after {POLL_TIMEOUT_S}s"
                )
            await asyncio.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
            poll = await client.get(get_url, headers=self._provider._headers())
            poll.raise_for_status()
            prediction = poll.json()
        if prediction.get("status") != "succeeded":
            raise RuntimeError(
                f"Replicate prediction failed: {prediction.get('error') or prediction}"
            )
        return prediction


class Replicate(BaseProvider):
    """Replicate REST client. Currently exposes segmentation only.

    Add new capabilities by attaching another handler in ``__init__``
    (e.g. ``self.upscale = ReplicateUpscale(self)``) — see the M5 plan
    in ``docs/poc-plan.md`` for the SAM 2 click-refine extension.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("REPLICATE_API_TOKEN", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.segmentation = ReplicateGroundedSAM(self)

    @property
    def name(self) -> str:
        return "replicate"

    def _headers(self) -> dict[str, str]:
        # Replicate uses standard Bearer auth; this override exists only
        # so the inheritance is explicit and easy to swap if Replicate
        # ever ships a v2 auth scheme.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
