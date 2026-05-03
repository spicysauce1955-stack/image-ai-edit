from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..models.base import (
    BaseProvider,
    ChatResponse,
    ImageModel,
    ImageResponse,
    Message,
    TextModel,
    ToolCall,
    Usage,
)
from ..config import get_env

DEFAULT_TEXT_MODEL = "MiniMax-M2.7"
DEFAULT_IMAGE_MODEL = "image-01"
BASE_URL = "https://api.minimaxi.com"


class MiniMaxText(TextModel):
    def __init__(self, provider: MiniMax) -> None:
        self._provider = provider

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse | AsyncIterator[str]:
        if stream:
            return self.chat_stream(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        payload: dict[str, Any] = {
            "model": model or DEFAULT_TEXT_MODEL,
            "messages": [self._format_msg(m) for m in messages],
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        payload.update(kwargs)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._provider.base_url}/v1/text/chatcompletion_v2",
                headers=self._provider._headers(),
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        usage_data = data.get("usage", {})
        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments", ""),
                )
            )

        return ChatResponse(
            id=data.get("id", ""),
            content=msg.get("content", ""),
            model=data.get("model", ""),
            finish_reason=choice.get("finish_reason", ""),
            usage=Usage(
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            tool_calls=tool_calls,
            raw=data,
        )

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": model or DEFAULT_TEXT_MODEL,
            "messages": [self._format_msg(m) for m in messages],
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        payload.update(kwargs)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._provider.base_url}/v1/text/chatcompletion_v2",
                headers=self._provider._headers(),
                json=payload,
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content

    @staticmethod
    def _format_msg(m: Message) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.name:
            msg["name"] = m.name
        return msg


class MiniMaxImage(ImageModel):
    def __init__(self, provider: MiniMax) -> None:
        self._provider = provider

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        size: str | None = None,
        n: int = 1,
        aspect_ratio: str | None = None,
        prompt_optimizer: bool = False,
        response_format: str = "url",
        seed: int | None = None,
        **kwargs: Any,
    ) -> ImageResponse:
        payload: dict[str, Any] = {
            "model": model or DEFAULT_IMAGE_MODEL,
            "prompt": prompt,
            "n": n,
            "prompt_optimizer": prompt_optimizer,
            "response_format": response_format,
        }
        if size is not None:
            payload["size"] = size
        if aspect_ratio is not None:
            payload["aspect_ratio"] = aspect_ratio
        if seed is not None:
            payload["seed"] = seed
        payload.update(kwargs)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._provider.base_url}/v1/image_generation",
                headers=self._provider._headers(),
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

        image_data = data.get("data", {})
        return ImageResponse(
            urls=image_data.get("image_urls", []),
            base64_data=image_data.get("image_base64", []),
            raw=data,
        )


class MiniMax(BaseProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("MINIMAX_API_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.text = MiniMaxText(self)
        self.image = MiniMaxImage(self)

    @property
    def name(self) -> str:
        return "minimax"