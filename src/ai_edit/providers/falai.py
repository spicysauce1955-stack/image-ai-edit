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
POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 180.0


def _data_uri(image_bytes: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


class FalAIRelight(EditModel):
    """IC-Light v2 relighting. Pass a single image; the instruction is used as the prompt."""

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
            resp = await client.post(target, headers=self._provider._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

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
        return {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }
