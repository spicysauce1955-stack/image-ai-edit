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
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


class ReplicateGroundedSAM(SegmentationModel):
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
        image_uri = _data_uri(image, mime_type)
        prompt_str = ",".join(p.strip() for p in prompts)

        payload: dict[str, Any] = {
            "input": {
                "image": image_uri,
                "mask_prompt": prompt_str,
                "negative_mask_prompt": kwargs.pop("negative_mask_prompt", ""),
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
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
