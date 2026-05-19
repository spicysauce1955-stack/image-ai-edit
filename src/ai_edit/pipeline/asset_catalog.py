"""Curated 3D-asset catalog backing the AR delivery layer.

Phase 2 of the AR plan. Replaces the original "image→3D provider" idea
with a manifest of pre-vetted free models on the web. The catalog feeds
the AR routes the same way Phase 1 did — assets land in the
:class:`~ai_edit.pipeline.ar_store.ARStore` under their ``id`` so
``/ar/<id>`` Just Works.

The manifest lives at ``assets/catalog.json`` (see :func:`default_path`)
and is a JSON object of the form::

    {
      "version": 1,
      "entries": [
        {
          "id": "box",
          "name": "Khronos Box",
          "category": "sample",
          "description": "...",
          "glb_url": "https://...",
          "usdz_url": null,
          "thumbnail_url": null,
          "license": "CC0",
          "attribution": "",
          "source_url": "https://github.com/KhronosGroup/glTF-Sample-Assets",
          "scale_hint": null
        }
      ]
    }

``version`` lets us evolve the schema without surprising older readers.
Today's loader handles ``version: 1`` only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ar_store import validate_scene_id

CATALOG_VERSION = 1


def default_path() -> Path:
    """Repo-root-relative path to the in-tree catalog manifest.

    Resolved relative to *this file* rather than ``Path.cwd()`` so the
    catalog is findable regardless of which directory the caller ran
    Python from.
    """
    return Path(__file__).resolve().parents[3] / "assets" / "catalog.json"


@dataclass(frozen=True)
class GlbBundleSource:
    """Bundle a remote .gltf + textures into a self-contained .glb.

    Used by entries whose source ships unbundled (Poly Haven, etc.).
    ``rewriter`` names a strategy registered in
    :mod:`asset_bundle.REWRITERS` (e.g. ``"poly_haven"``); ``None``
    selects the default urljoin-based rewriter.
    """

    gltf_url: str
    rewriter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"gltf_url": self.gltf_url, "rewriter": self.rewriter}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GlbBundleSource:
        if "gltf_url" not in raw:
            raise ValueError("glb_bundle missing required 'gltf_url'")
        return cls(gltf_url=raw["gltf_url"], rewriter=raw.get("rewriter"))


@dataclass(frozen=True)
class AssetCatalogEntry:
    """One row in the catalog manifest.

    ``id`` is the value used as ``<scene_id>`` in the AR URLs
    (``/ar/<id>``) and the on-disk directory name in the
    :class:`FilesystemARStore`. It must satisfy
    :data:`ar_store.SCENE_ID_PATTERN` — enforced at load time so a bad
    manifest fails fast.

    At least one of ``glb_url`` / ``usdz_url`` / ``glb_bundle`` must be
    present; otherwise the entry serves no purpose.

    ``glb_bundle`` is mutually exclusive with ``glb_url``: when set, the
    fetcher pulls the .gltf + textures through the bundler and writes
    the resulting self-contained GLB to the store, so there's no
    separate "direct" GLB URL.

    ``scale_hint`` is a multiplier the AR client may apply to bring the
    model to real-world scale (1.0 means "model is already authored at
    metres"). ``None`` means "unknown — use the model's native scale".
    """

    id: str
    name: str
    category: str
    description: str
    glb_url: str | None
    usdz_url: str | None
    thumbnail_url: str | None
    license: str
    attribution: str
    source_url: str
    scale_hint: float | None = None
    glb_bundle: GlbBundleSource | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize as the JSON manifest row.

        Mirrors the field order in :meth:`from_dict` so a load → dump
        round-trip is exact.
        """
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "glb_url": self.glb_url,
            "usdz_url": self.usdz_url,
            "thumbnail_url": self.thumbnail_url,
            "license": self.license,
            "attribution": self.attribution,
            "source_url": self.source_url,
            "scale_hint": self.scale_hint,
            "glb_bundle": self.glb_bundle.to_dict() if self.glb_bundle else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AssetCatalogEntry:
        """Parse one manifest row.

        Validates required fields and the scene-id format. Unknown
        fields are ignored so we can add metadata later without
        breaking existing callers.
        """
        required = ("id", "name", "category", "license", "source_url")
        missing = [k for k in required if k not in raw]
        if missing:
            raise ValueError(f"Catalog entry missing required fields: {missing!r}")

        entry_id = raw["id"]
        try:
            validate_scene_id(entry_id)
        except ValueError as exc:
            raise ValueError(f"Catalog entry id {entry_id!r} is invalid: {exc}") from exc

        glb = raw.get("glb_url")
        usdz = raw.get("usdz_url")
        bundle_raw = raw.get("glb_bundle")
        bundle = GlbBundleSource.from_dict(bundle_raw) if bundle_raw else None

        if glb and bundle:
            raise ValueError(
                f"Catalog entry {entry_id!r} has both glb_url and glb_bundle; "
                f"choose one — glb_bundle generates the GLB itself."
            )
        if not glb and not usdz and not bundle:
            raise ValueError(
                f"Catalog entry {entry_id!r} has none of glb_url / usdz_url / glb_bundle; "
                f"at least one asset source is required."
            )

        return cls(
            id=entry_id,
            name=raw["name"],
            category=raw["category"],
            description=raw.get("description", ""),
            glb_url=glb,
            usdz_url=usdz,
            thumbnail_url=raw.get("thumbnail_url"),
            license=raw["license"],
            attribution=raw.get("attribution", ""),
            source_url=raw["source_url"],
            scale_hint=raw.get("scale_hint"),
            glb_bundle=bundle,
        )


class AssetCatalog:
    """Read-only view over a catalog manifest.

    Cheap to construct — the entire manifest is held in memory. Routes
    that need it should either build a new instance at app start
    (current usage) or pass an injected catalog through dependency
    injection (future, when we want hot-reload).
    """

    def __init__(self, entries: list[AssetCatalogEntry]) -> None:
        # Reject duplicates here rather than silently letting later
        # entries shadow earlier ones — a duplicate id in the manifest
        # is almost always a copy-paste bug.
        seen: set[str] = set()
        for entry in entries:
            if entry.id in seen:
                raise ValueError(f"Duplicate catalog id: {entry.id!r}")
            seen.add(entry.id)
        self._entries: list[AssetCatalogEntry] = list(entries)
        self._by_id: dict[str, AssetCatalogEntry] = {e.id: e for e in self._entries}

    @classmethod
    def load(cls, path: Path | str | None = None) -> AssetCatalog:
        """Load a catalog from ``path`` (default: in-tree manifest)."""
        manifest_path = Path(path) if path is not None else default_path()
        raw = json.loads(manifest_path.read_text())
        version = raw.get("version")
        if version != CATALOG_VERSION:
            raise ValueError(
                f"Unsupported catalog version: {version!r} "
                f"(this build understands {CATALOG_VERSION})"
            )
        entries_raw = raw.get("entries", [])
        if not isinstance(entries_raw, list):
            raise ValueError("Catalog 'entries' must be a list")
        entries = [AssetCatalogEntry.from_dict(e) for e in entries_raw]
        return cls(entries)

    def list(self, category: str | None = None) -> list[AssetCatalogEntry]:
        """Return entries in manifest order, optionally filtered."""
        if category is None:
            return list(self._entries)
        return [e for e in self._entries if e.category == category]

    def get(self, asset_id: str) -> AssetCatalogEntry | None:
        """Return the entry for ``asset_id`` or ``None`` if missing."""
        return self._by_id.get(asset_id)

    def categories(self) -> list[str]:
        """Return distinct categories in first-seen order."""
        seen: list[str] = []
        for entry in self._entries:
            if entry.category not in seen:
                seen.append(entry.category)
        return seen

    def __len__(self) -> int:
        return len(self._entries)
