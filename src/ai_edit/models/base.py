from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    role: str
    content: str
    name: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResponse:
    id: str = ""
    content: str = ""
    model: str = ""
    finish_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResponse:
    urls: list[str] = field(default_factory=list)
    base64_data: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SegmentationMask:
    label: str
    image_bytes: bytes
    mime_type: str = "image/png"


@dataclass
class SegmentationResponse:
    masks: list[SegmentationMask] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EditResponse:
    image_bytes: bytes = b""
    mime_type: str = "image/png"
    text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class BaseProvider:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    @abstractmethod
    def name(self) -> str: ...

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


class TextModel(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse | AsyncIterator[str]: ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...


class ImageModel(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        size: str | None = None,
        n: int = 1,
        **kwargs: Any,
    ) -> ImageResponse: ...


class SegmentationModel(ABC):
    @abstractmethod
    async def segment(
        self,
        image: bytes,
        prompts: list[str],
        *,
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> SegmentationResponse: ...


class EditModel(ABC):
    @abstractmethod
    async def edit(
        self,
        instruction: str,
        images: list[tuple[bytes, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> EditResponse: ...