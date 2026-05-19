"""HTTP tests for the catalog routes.

Phase 3.A. Builds a tiny in-memory :class:`AssetCatalog` and injects it
into the app so the tests are independent of the on-disk
``assets/catalog.json`` manifest.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_edit.pipeline.asset_catalog import AssetCatalog, AssetCatalogEntry
from ai_edit.server.app import create_app


def _entry(id: str, category: str = "sample") -> AssetCatalogEntry:
    return AssetCatalogEntry.from_dict(
        {
            "id": id,
            "name": id.title(),
            "category": category,
            "description": "",
            "glb_url": f"https://example.invalid/{id}.glb",
            "usdz_url": None,
            "thumbnail_url": None,
            "license": "CC0-1.0",
            "attribution": "",
            "source_url": "https://example.invalid",
            "scale_hint": None,
        }
    )


@pytest.fixture
def catalog() -> AssetCatalog:
    return AssetCatalog(
        [
            _entry("alpha", "sample"),
            _entry("beta", "sample"),
            _entry("fence_a", "fence"),
        ]
    )


@pytest.fixture
def client(catalog: AssetCatalog) -> TestClient:
    return TestClient(create_app(catalog=catalog))


class TestListEntries:
    def test_returns_all_entries(self, client: TestClient) -> None:
        r = client.get("/api/catalog")
        assert r.status_code == 200
        payload = r.json()
        assert [e["id"] for e in payload] == ["alpha", "beta", "fence_a"]

    def test_filter_by_category(self, client: TestClient) -> None:
        r = client.get("/api/catalog", params={"category": "fence"})
        assert r.status_code == 200
        assert [e["id"] for e in r.json()] == ["fence_a"]

    def test_filter_unknown_category_returns_empty_list(
        self, client: TestClient
    ) -> None:
        r = client.get("/api/catalog", params={"category": "missing"})
        assert r.status_code == 200
        assert r.json() == []

    def test_payload_includes_derived_ar_urls(self, client: TestClient) -> None:
        # Frontends shouldn't have to hard-code path templates — the
        # API delivers absolute paths for the AR route and the GLB.
        r = client.get("/api/catalog")
        first = r.json()[0]
        assert first["ar_url"] == "/ar/alpha"
        assert first["glb_local_url"] == "/ar/alpha/model.glb"
        assert first["usdz_local_url"] is None


class TestGetEntry:
    def test_returns_existing_entry(self, client: TestClient) -> None:
        r = client.get("/api/catalog/alpha")
        assert r.status_code == 200
        entry = r.json()
        assert entry["id"] == "alpha"
        assert entry["ar_url"] == "/ar/alpha"

    def test_404_for_missing(self, client: TestClient) -> None:
        r = client.get("/api/catalog/nope")
        assert r.status_code == 404


class TestCategories:
    def test_returns_distinct_categories(self, client: TestClient) -> None:
        r = client.get("/api/catalog/categories")
        assert r.status_code == 200
        assert r.json() == ["sample", "fence"]

    def test_categories_route_not_shadowed_by_id_param(
        self, client: TestClient
    ) -> None:
        # Regression guard: if route registration order ever flips,
        # ``/api/catalog/categories`` would hit the {asset_id} handler
        # and 404 looking for a "categories" entry.
        r = client.get("/api/catalog/categories")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert "sample" in r.json()
