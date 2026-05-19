"""Unit tests for AssetCatalogEntry + AssetCatalog.

Phase 2.A. Schema + loader only — no downloads, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_edit.pipeline.asset_catalog import (
    CATALOG_VERSION,
    AssetCatalog,
    AssetCatalogEntry,
    default_path,
)


def _minimal_raw_entry(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": "test_asset",
        "name": "Test Asset",
        "category": "sample",
        "description": "",
        "glb_url": "https://example.invalid/asset.glb",
        "usdz_url": None,
        "thumbnail_url": None,
        "license": "CC0-1.0",
        "attribution": "",
        "source_url": "https://example.invalid",
        "scale_hint": None,
    }
    raw.update(overrides)
    return raw


class TestAssetCatalogEntry:
    def test_round_trip_via_dict(self) -> None:
        entry = AssetCatalogEntry.from_dict(_minimal_raw_entry())
        again = AssetCatalogEntry.from_dict(entry.to_dict())
        assert again == entry

    def test_from_dict_rejects_missing_required(self) -> None:
        raw = _minimal_raw_entry()
        del raw["name"]
        with pytest.raises(ValueError, match="missing required"):
            AssetCatalogEntry.from_dict(raw)

    def test_from_dict_rejects_invalid_id(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            AssetCatalogEntry.from_dict(_minimal_raw_entry(id="bad id!"))

    def test_from_dict_rejects_no_asset_url(self) -> None:
        # An entry with neither GLB nor USDZ is useless — the route
        # would 404 on both asset paths.
        with pytest.raises(ValueError, match="at least one asset URL"):
            AssetCatalogEntry.from_dict(_minimal_raw_entry(glb_url=None, usdz_url=None))

    def test_from_dict_accepts_usdz_only(self) -> None:
        # iOS-only entries (Apple AR Quick Look gallery) ship USDZ but
        # no GLB. Must be valid.
        entry = AssetCatalogEntry.from_dict(
            _minimal_raw_entry(glb_url=None, usdz_url="https://example.invalid/x.usdz")
        )
        assert entry.glb_url is None
        assert entry.usdz_url == "https://example.invalid/x.usdz"

    def test_from_dict_ignores_unknown_fields(self) -> None:
        # Forward-compat: adding fields to the manifest must not break
        # older loaders.
        raw = _minimal_raw_entry()
        raw["future_field"] = "something"
        entry = AssetCatalogEntry.from_dict(raw)
        assert entry.id == "test_asset"

    def test_frozen_dataclass_is_hashable(self) -> None:
        # frozen=True lets us use entries as dict keys / set members
        # without surprise mutation. Smoke test.
        e1 = AssetCatalogEntry.from_dict(_minimal_raw_entry())
        e2 = AssetCatalogEntry.from_dict(_minimal_raw_entry())
        assert {e1, e2} == {e1}


class TestAssetCatalog:
    def _two_entries(self) -> list[AssetCatalogEntry]:
        return [
            AssetCatalogEntry.from_dict(_minimal_raw_entry(id="a", category="sample")),
            AssetCatalogEntry.from_dict(_minimal_raw_entry(id="b", category="fence")),
        ]

    def test_list_returns_all_in_order(self) -> None:
        catalog = AssetCatalog(self._two_entries())
        ids = [e.id for e in catalog.list()]
        assert ids == ["a", "b"]

    def test_list_filtered_by_category(self) -> None:
        catalog = AssetCatalog(self._two_entries())
        assert [e.id for e in catalog.list("fence")] == ["b"]
        assert catalog.list("missing") == []

    def test_get_returns_entry(self) -> None:
        catalog = AssetCatalog(self._two_entries())
        entry = catalog.get("a")
        assert entry is not None
        assert entry.id == "a"

    def test_get_missing_returns_none(self) -> None:
        catalog = AssetCatalog(self._two_entries())
        assert catalog.get("nope") is None

    def test_categories_first_seen_order(self) -> None:
        catalog = AssetCatalog(
            [
                AssetCatalogEntry.from_dict(_minimal_raw_entry(id="a", category="sample")),
                AssetCatalogEntry.from_dict(_minimal_raw_entry(id="b", category="fence")),
                AssetCatalogEntry.from_dict(_minimal_raw_entry(id="c", category="sample")),
            ]
        )
        assert catalog.categories() == ["sample", "fence"]

    def test_rejects_duplicate_ids(self) -> None:
        with pytest.raises(ValueError, match="Duplicate"):
            AssetCatalog(
                [
                    AssetCatalogEntry.from_dict(_minimal_raw_entry(id="dup")),
                    AssetCatalogEntry.from_dict(_minimal_raw_entry(id="dup")),
                ]
            )

    def test_len(self) -> None:
        catalog = AssetCatalog(self._two_entries())
        assert len(catalog) == 2

    def test_load_from_file(self, tmp_path: Path) -> None:
        manifest = {
            "version": CATALOG_VERSION,
            "entries": [_minimal_raw_entry(id="alpha"), _minimal_raw_entry(id="beta")],
        }
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps(manifest))
        catalog = AssetCatalog.load(path)
        assert [e.id for e in catalog.list()] == ["alpha", "beta"]

    def test_load_rejects_wrong_version(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps({"version": 999, "entries": []}))
        with pytest.raises(ValueError, match="version"):
            AssetCatalog.load(path)

    def test_load_rejects_non_list_entries(self, tmp_path: Path) -> None:
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps({"version": CATALOG_VERSION, "entries": {}}))
        with pytest.raises(ValueError, match="must be a list"):
            AssetCatalog.load(path)


class TestInTreeCatalog:
    def test_default_path_resolves(self) -> None:
        # The default catalog must be present in the repo — without it
        # the AR routes have nothing to deliver.
        assert default_path().is_file(), f"missing catalog at {default_path()}"

    def test_default_catalog_loads_and_has_entries(self) -> None:
        catalog = AssetCatalog.load()
        assert len(catalog) >= 1
        # Box is the canonical sanity entry; if it ever disappears,
        # update fetch_ar_demo's expectations alongside this test.
        assert catalog.get("box") is not None

    def test_default_catalog_ids_are_url_safe(self) -> None:
        # Defence-in-depth: validate_scene_id is already called in
        # from_dict, but verify the loaded catalog upholds it.
        from ai_edit.pipeline.ar_store import validate_scene_id

        catalog = AssetCatalog.load()
        for entry in catalog.list():
            validate_scene_id(entry.id)
