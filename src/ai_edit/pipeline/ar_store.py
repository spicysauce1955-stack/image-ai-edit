"""Storage abstraction for AR-deliverable 3D assets.

Phase 1 of the AR plan: serve pre-placed GLB / USDZ assets to a
``<model-viewer>`` page over the existing FastAPI server. This module
keeps the storage layer behind an ABC so the in-tree filesystem
implementation can later be swapped for object storage (Cloudflare R2,
S3) without touching the route handlers.

The mapping from MIME type to on-disk filename is centralized here so
generators, the AR routes, and the manual-smoke fetch script all use
the same names. A ``model.glb`` on disk is always glTF binary; a
``model.usdz`` is always USDZ. Don't put a USDZ at ``model.glb`` —
Quick Look will refuse to render it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models.base import (
    MIME_GLB,
    MIME_GLTF_JSON,
    MIME_USDZ,
    Scene3DAsset,
)

# Canonical MIME → on-disk filename mapping. Kept tiny on purpose: every
# format we serve needs an explicit entry, and an unknown MIME is a
# programming error rather than a fall-through to a generic name.
_MIME_TO_FILENAME: dict[str, str] = {
    MIME_GLB: "model.glb",
    MIME_USDZ: "model.usdz",
    MIME_GLTF_JSON: "model.gltf",
}


def filename_for_mime(mime_type: str) -> str | None:
    """Return the canonical on-disk filename for ``mime_type``, or
    ``None`` if the type isn't one we serve.

    Exposed at module level so the routes can use the same mapping when
    reverse-engineering a URL → MIME without having to instantiate a
    store.
    """
    return _MIME_TO_FILENAME.get(mime_type)


class ARStore(ABC):
    """Pluggable storage for AR assets keyed by ``scene_id`` + MIME.

    The interface is deliberately small: ``exists``, ``get``, ``put``.
    Listing, deletion, and TTL are out of scope for Phase 1 — when
    those become necessary, add them here so every backend is forced
    to implement them.
    """

    @abstractmethod
    def exists(self, scene_id: str) -> bool:
        """``True`` if any asset for ``scene_id`` is present."""

    @abstractmethod
    def get(self, scene_id: str, mime_type: str) -> bytes | None:
        """Return the bytes for ``mime_type`` under ``scene_id``, or
        ``None`` if no such asset exists.

        Unknown MIME types always return ``None`` (rather than raise);
        this lets the AR routes return a clean 404 for unsupported
        formats without a try/except around every call.
        """

    @abstractmethod
    def put(self, scene_id: str, asset: Scene3DAsset) -> None:
        """Persist ``asset`` for ``scene_id``.

        The implementation is responsible for creating intermediate
        directories / buckets as needed. Overwrites silently — callers
        wanting "don't clobber" semantics should check :meth:`exists`
        first.
        """


class FilesystemARStore(ARStore):
    """Filesystem-backed :class:`ARStore`.

    Layout::

        <root>/
            <scene_id>/
                model.glb
                model.usdz
                model.gltf      # rare; only when a provider returns gltf+json

    ``root`` is created lazily on first ``put``. The store does **not**
    validate ``scene_id`` — that's the AR route's job (see the regex on
    the route's path parameter) so the validation policy stays in one
    place.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _scene_dir(self, scene_id: str) -> Path:
        return self.root / scene_id

    def exists(self, scene_id: str) -> bool:
        scene_dir = self._scene_dir(scene_id)
        if not scene_dir.is_dir():
            return False
        return any(scene_dir.iterdir())

    def get(self, scene_id: str, mime_type: str) -> bytes | None:
        filename = filename_for_mime(mime_type)
        if filename is None:
            return None
        target = self._scene_dir(scene_id) / filename
        if not target.is_file():
            return None
        return target.read_bytes()

    def put(self, scene_id: str, asset: Scene3DAsset) -> None:
        filename = filename_for_mime(asset.mime_type)
        if filename is None:
            raise ValueError(
                f"Cannot store asset with unsupported MIME type {asset.mime_type!r}; "
                f"add it to ar_store._MIME_TO_FILENAME if it's a real format."
            )
        scene_dir = self._scene_dir(scene_id)
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / filename).write_bytes(asset.data)
