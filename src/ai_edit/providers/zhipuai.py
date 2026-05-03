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

DEFAULT_TEXT_MODEL = "glm-5.1"
DEFAULT_IMAGE_MODEL = "glm-image"
BASE_URL = "https://open.bigmodel.cn/api"


class ZhipuAIText(TextModel):
    def __init__(self, provider: ZhipuAI) -> None:
        self._provider = provider

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        top_p: float | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncIterator[str]:
        if stream:
            return self.chat_stream(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                **kwargs,
            )

        payload: dict[str, Any] = {
            "model": model or DEFAULT_TEXT_MODEL,
            "messages": [self._format_msg(m) for m in messages],
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._provider.base_url}/paas/v4/chat/completions",
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
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
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
        top_p: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": model or DEFAULT_TEXT_MODEL,
            "messages": [self._format_msg(m) for m in messages],
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._provider.base_url}/paas/v4/chat/completions",
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
        return {"role": m.role, "content": m.content}


class ZhipuAIImage(ImageModel):
    def __init__(self, provider: ZhipuAI) -> None:
        self._provider = provider

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        size: str | None = None,
        n: int = 1,
        quality: str | None = None,
        **kwargs: Any,
    ) -> ImageResponse:
        payload: dict[str, Any] = {
            "model": model or DEFAULT_IMAGE_MODEL,
            "prompt": prompt,
        }
        if size is not None:
            payload["size"] = size
        if quality is not None:
            payload["quality"] = quality
        payload.update(kwargs)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._provider.base_url}/paas/v4/images/generations",
                headers=self._provider._headers(),
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

        urls = [item["url"] for item in data.get("data", []) if "url" in item]
        return ImageResponse(
            urls=urls,
            raw=data,
        )


class ZhipuAI(BaseProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key or get_env("ZHIPUAI_API_KEY", required=True)
        super().__init__(api_key=key, base_url=base_url)
        self.text = ZhipuAIText(self)
        self.image = ZhipuAIImage(self)

    @property
    def name(self) -> str:
        return "zhipuai"