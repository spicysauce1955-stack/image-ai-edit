"""Provider-agnostic capability interfaces and response dataclasses.

Re-exports the most commonly used names from :mod:`.base` so callers
can write ``from ai_edit.models import EditResponse`` instead of
reaching into the submodule.
"""

from .base import (
    BaseProvider,
    ChatResponse,
    EditModel,
    EditResponse,
    ImageModel,
    ImageResponse,
    Message,
    SegmentationMask,
    SegmentationModel,
    SegmentationResponse,
    TextModel,
    ToolCall,
    Usage,
)

__all__ = [
    "BaseProvider",
    "ChatResponse",
    "EditModel",
    "EditResponse",
    "ImageModel",
    "ImageResponse",
    "Message",
    "SegmentationMask",
    "SegmentationModel",
    "SegmentationResponse",
    "TextModel",
    "ToolCall",
    "Usage",
]
