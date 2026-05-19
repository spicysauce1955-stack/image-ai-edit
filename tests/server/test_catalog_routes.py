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


class TestBrowsePage:
    def test_returns_html(self, client: TestClient) -> None:
        r = client.get("/catalog")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")

    def test_lists_all_entries(self, client: TestClient) -> None:
        r = client.get("/catalog")
        body = r.text
        # Names appear in their title-case form via _entry().
        assert "Alpha" in body
        assert "Beta" in body
        assert "Fence_A" in body

    def test_each_card_links_to_ar_route(self, client: TestClient) -> None:
        # The whole point of the browse page is to get to /ar/<id>.
        r = client.get("/catalog")
        body = r.text
        assert 'href="/ar/alpha"' in body
        assert 'href="/ar/beta"' in body
        assert 'href="/ar/fence_a"' in body

    def test_count_reflects_catalog(self, client: TestClient) -> None:
        r = client.get("/catalog")
        assert "3 models" in r.text

    def test_empty_catalog_renders_empty_state(self) -> None:
        empty = AssetCatalog([])
        c = TestClient(create_app(catalog=empty))
        r = c.get("/catalog")
        assert r.status_code == 200
        assert "No models" in r.text
        assert "0 models" in r.text

    def test_attribution_rendered_when_present(self) -> None:
        # CC-BY entries must surface the attribution on the page;
        # CC0 entries omit the "by ..." line.
        entry_attr = AssetCatalogEntry.from_dict(
            {
                "id": "with_attr",
                "name": "With Attribution",
                "category": "sample",
                "description": "",
                "glb_url": "https://example.invalid/x.glb",
                "usdz_url": None,
                "thumbnail_url": None,
                "license": "CC-BY-4.0",
                "attribution": "Jane Modeler",
                "source_url": "https://example.invalid",
                "scale_hint": None,
            }
        )
        entry_no_attr = AssetCatalogEntry.from_dict(
            {
                "id": "no_attr",
                "name": "No Attribution",
                "category": "sample",
                "description": "",
                "glb_url": "https://example.invalid/y.glb",
                "usdz_url": None,
                "thumbnail_url": None,
                "license": "CC0-1.0",
                "attribution": "",
                "source_url": "https://example.invalid",
                "scale_hint": None,
            }
        )
        c = TestClient(create_app(catalog=AssetCatalog([entry_attr, entry_no_attr])))
        body = c.get("/catalog").text
        assert "by Jane Modeler" in body
        # Make sure we didn't render an empty 'by ' line for the CC0
        # entry — that would look bad in the UI.
        assert ">by </div>" not in body
