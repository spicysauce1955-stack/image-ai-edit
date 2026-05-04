"""Provider-agnostic data models and abstract base classes.

Every concrete provider in :mod:`ai_edit.providers` implements one or more
of the abstract capability classes defined here:

- :class:`TextModel` — chat completion (streaming and non-streaming).
- :class:`ImageModel` — text-to-image generation.
- :class:`SegmentationModel` — image → per-label binary masks.
- :class:`EditModel` — multi-image edit / object insertion.

The dataclasses below normalize provider responses into a shape the rest
of the codebase can consume without knowing which vendor produced them.
The original wire response is always preserved on a ``raw`` field so
caller code can reach for vendor-specific extras when needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """A single chat message.

    ``name`` is only used by providers that support function-call style
    role attribution (e.g. ``tool``/``function`` messages).
    """

    role: str
    content: str
    name: str | None = None


@dataclass
class ToolCall:
    """A tool invocation requested by a chat model."""

    id: str
    name: str
    arguments: str


@dataclass
class Usage:
    """Token usage reported by a chat model.

    Providers vary in which fields they populate. Treat zeros as
    "unknown" rather than "actually zero".
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResponse:
    """Normalized chat completion response."""

    id: str = ""
    content: str = ""
    model: str = ""
    finish_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResponse:
    """Normalized text-to-image response.

    Some vendors return URLs, others return inline base64. Both fields
    are populated when available; consumers should check ``urls`` first
    and fall back to ``base64_data``.
    """

    urls: list[str] = field(default_factory=list)
    base64_data: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SegmentationMask:
    """A single binary mask returned by a segmentation provider.

    ``label`` echoes back the prompt that produced the mask (e.g.
    ``"trees"``). ``image_bytes`` is a decoded image (typically a PNG)
    where white pixels mark the segmented region — the exact encoding
    depends on the upstream model, so callers wanting a numpy array
    should decode through PIL/OpenCV.
    """

    label: str
    image_bytes: bytes
    mime_type: str = "image/png"


@dataclass
class SegmentationResponse:
    """Collection of masks returned by one segmentation call."""

    masks: list[SegmentationMask] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EditResponse:
    """Result of a multi-image edit / object-insertion call.

    ``text`` captures any commentary the model returned alongside the
    image (Gemini in particular sometimes narrates the edit). It is safe
    to ignore for the happy path but useful when debugging refusals or
    truncated outputs.
    """

    image_bytes: bytes = b""
    mime_type: str = "image/png"
    text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class BaseProvider:
    """Common state shared by every provider.

    Subclasses are expected to attach capability handlers (``self.text``,
    ``self.image``, ``self.segmentation``, etc.) and override
    :meth:`_headers` if the vendor uses a non-Bearer auth scheme.
    """

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable lowercase identifier (e.g. ``"gemini"``). Used in logs."""
        ...

    def _headers(self) -> dict[str, str]:
        """Default Bearer-token JSON headers.

        Override in subclasses for vendors that use a different scheme
        (Gemini uses ``x-goog-api-key``, fal.ai uses ``Key <key>``).
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


class TextModel(ABC):
    """Chat completion capability."""

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
    ) -> ChatResponse | AsyncIterator[str]:
        """Run a chat completion.

        When ``stream=True`` the implementation should return the async
        iterator from :meth:`chat_stream` (yielding text chunks) rather
        than a :class:`ChatResponse`.
        """
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion as text chunks."""
        ...


class ImageModel(ABC):
    """Text-to-image generation capability."""

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
    """Open-vocabulary image segmentation capability.

    ``prompts`` is a list of natural-language labels (e.g.
    ``["ground", "trees", "sky"]``). The implementation is expected to
    return one :class:`SegmentationMask` per prompt that yielded a
    detection (some providers may return fewer if a label produced no
    matches; the POC pipeline is robust to that).
    """

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
    """Multi-image edit capability — the heart of the insertion pipeline.

    Implementations take a free-form ``instruction`` plus a list of
    ``(image_bytes, mime_type)`` tuples. Convention used by the POC
    pipeline:

    - Image 0 is the **scene** (the photo to edit into).
    - Image 1 is the **reference object** (what to insert).
    - Optional images that follow may carry masks or extra references,
      and should be addressed explicitly from the prompt
      (e.g. "the white area in image 3 is where the object goes").

    Not every vendor honors a binary mask channel; those that do
    (OpenAI gpt-image-1) should expose it via ``**kwargs`` rather than
    polluting this base signature.
    """

    @abstractmethod
    async def edit(
        self,
        instruction: str,
        images: list[tuple[bytes, str]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> EditResponse: ...
