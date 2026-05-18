"""Provider-agnostic capability interfaces and response dataclasses.

Re-exports the most commonly used names from :mod:`.base` so callers
can write ``from ai_edit.models import EditResponse`` instead of
reaching into the submodule.
"""

from .base import (
    MIME_GLB,
    MIME_GLTF_JSON,
    MIME_USDZ,
    BaseProvider,
    ChatResponse,
    EditModel,
    EditResponse,
    Format3DConverter,
    ImageModel,
    ImageResponse,
    Message,
    Scene3DAsset,
    Scene3DModel,
    Scene3DResponse,
    SegmentationMask,
    SegmentationModel,
    SegmentationResponse,
    TextModel,
    ToolCall,
    Usage,
)

__all__ = [
    "MIME_GLB",
    "MIME_GLTF_JSON",
    "MIME_USDZ",
    "BaseProvider",
    "ChatResponse",
    "EditModel",
    "EditResponse",
    "Format3DConverter",
    "ImageModel",
    "ImageResponse",
    "Message",
    "Scene3DAsset",
    "Scene3DModel",
    "Scene3DResponse",
    "SegmentationMask",
    "SegmentationModel",
    "SegmentationResponse",
    "TextModel",
    "ToolCall",
    "Usage",
]
