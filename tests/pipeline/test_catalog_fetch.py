"""Unit tests for the catalog fetcher.

All HTTP is mocked via :class:`httpx.MockTransport` so the suite stays
offline. A separate network-gated test exists for live URLs (lives in
``tests/pipeline/test_catalog_fetch_network.py`` — Phase 2.C).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ai_edit.models import MIME_GLB, MIME_USDZ
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.pipeline.asset_catalog import AssetCatalog, AssetCatalogEntry
from ai_edit.pipeline.catalog_fetch import (
    fetch_all,
    fetch_entry,
    format_summary,
    select_entries,
)


def _entry(
    *,
    id: str = "test",
    glb_url: str | None = "https://example.invalid/x.glb",
    usdz_url: str | None = None,
) -> AssetCatalogEntry:
    return AssetCatalogEntry.from_dict(
        {
            "id": id,
            "name": id,
            "category": "sample",
            "description": "",
            "glb_url": glb_url,
            "usdz_url": usdz_url,
            "thumbnail_url": None,
            "license": "CC0-1.0",
            "attribution": "",
            "source_url": "https://example.invalid",
            "scale_hint": None,
        }
    )


def _client(handler) -> httpx.Client:
    """Build an httpx.Client wired to a MockTransport ``handler``."""
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


class TestFetchEntry:
    def test_writes_glb_bytes_to_store(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://example.invalid/x.glb"
            return httpx.Response(200, content=b"GLB-BYTES-HERE")

        store = FilesystemARStore(tmp_path)
        with _client(handler) as client:
            result = fetch_entry(_entry(), store, client=client)

        assert result.glb.bytes_written == len(b"GLB-BYTES-HERE")
        assert result.glb.error is None
        assert store.get("test", MIME_GLB) == b"GLB-BYTES-HERE"

    def test_writes_both_glb_and_usdz(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith(".glb"):
                return httpx.Response(200, content=b"GLB")
            if str(request.url).endswith(".usdz"):
                return httpx.Response(200, content=b"USDZ")
            return httpx.Response(404)

        store = FilesystemARStore(tmp_path)
        with _client(handler) as client:
            result = fetch_entry(
                _entry(usdz_url="https://example.invalid/x.usdz"),
                store,
                client=client,
            )

        assert result.glb.bytes_written == 3
        assert result.usdz.bytes_written == 4
        assert store.get("test", MIME_GLB) == b"GLB"
        assert store.get("test", MIME_USDZ) == b"USDZ"

    def test_404_on_glb_records_error_but_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        store = FilesystemARStore(tmp_path)
        with _client(handler) as client:
            result = fetch_entry(_entry(), store, client=client)

        assert result.glb.bytes_written is None
        assert result.glb.error is not None
        assert "404" in result.glb.error or "HTTPStatusError" in result.glb.error
        # Nothing should have been written to the store.
        assert store.get("test", MIME_GLB) is None

    def test_usdz_failure_does_not_block_glb(self, tmp_path: Path) -> None:
        # A common real-world scenario: source has GLB but USDZ URL is
        # stale. GLB must still land successfully.
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith(".glb"):
                return httpx.Response(200, content=b"GLB")
            return httpx.Response(404)

        store = FilesystemARStore(tmp_path)
        with _client(handler) as client:
            result = fetch_entry(
                _entry(usdz_url="https://example.invalid/x.usdz"),
                store,
                client=client,
            )

        assert result.glb.ok
        assert not result.usdz.ok
        assert result.usdz.error is not None
        assert store.get("test", MIME_GLB) == b"GLB"
        assert store.get("test", MIME_USDZ) is None

    def test_no_url_marks_skipped_not_error(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"GLB")

        store = FilesystemARStore(tmp_path)
        with _client(handler) as client:
            # GLB only — USDZ url is None
            result = fetch_entry(_entry(usdz_url=None), store, client=client)

        assert result.glb.ok
        assert result.usdz.bytes_written is None
        assert result.usdz.error is None  # skipped, not errored
        assert result.usdz.skipped_reason is not None

    def test_bundle_source_routes_through_bundler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When an entry has glb_bundle (no glb_url), the fetcher must
        # call into the bundler rather than trying a direct GET on a
        # non-existent glb_url. Verify by stubbing bundle_remote_gltf.
        from ai_edit.pipeline import catalog_fetch
        from ai_edit.pipeline.asset_bundle import poly_haven_rewriter

        calls: dict[str, object] = {}

        def fake_bundle(gltf_url: str, *, client, rewriter):
            calls["gltf_url"] = gltf_url
            calls["rewriter"] = rewriter
            return b"FAKE-BUNDLED-GLB"

        monkeypatch.setattr(catalog_fetch, "bundle_remote_gltf", fake_bundle)

        entry = AssetCatalogEntry.from_dict(
            {
                "id": "ph_test",
                "name": "Poly Haven Test",
                "category": "outdoor",
                "description": "",
                "glb_url": None,
                "usdz_url": None,
                "thumbnail_url": None,
                "license": "CC0-1.0",
                "attribution": "",
                "source_url": "https://example.invalid",
                "scale_hint": None,
                "glb_bundle": {
                    "gltf_url": "https://example.invalid/x.gltf",
                    "rewriter": "poly_haven",
                },
            }
        )

        store = FilesystemARStore(tmp_path)
        # The httpx client isn't actually used because fake_bundle
        # short-circuits — but the fetcher creates one, so give it
        # something inert.
        def handler(_: httpx.Request) -> httpx.Response:  # pragma: no cover
            return httpx.Response(500)

        with _client(handler) as client:
            result = fetch_entry(entry, store, client=client)

        assert calls["gltf_url"] == "https://example.invalid/x.gltf"
        assert calls["rewriter"] is poly_haven_rewriter
        assert result.glb.bytes_written == len(b"FAKE-BUNDLED-GLB")
        assert store.get("ph_test", MIME_GLB) == b"FAKE-BUNDLED-GLB"


class TestSelectEntries:
    def _catalog(self) -> AssetCatalog:
        return AssetCatalog([_entry(id="a"), _entry(id="b"), _entry(id="c")])

    def test_none_returns_all(self) -> None:
        catalog = self._catalog()
        assert [e.id for e in select_entries(catalog, None)] == ["a", "b", "c"]

    def test_filter_preserves_request_order(self) -> None:
        catalog = self._catalog()
        assert [e.id for e in select_entries(catalog, ["c", "a"])] == ["c", "a"]

    def test_unknown_id_raises(self) -> None:
        catalog = self._catalog()
        with pytest.raises(KeyError, match="unknown catalog id"):
            select_entries(catalog, ["a", "missing"])


class TestFetchAll:
    def test_fetches_every_entry(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x")

        store = FilesystemARStore(tmp_path)
        catalog = AssetCatalog([_entry(id="a"), _entry(id="b")])
        with _client(handler) as client:
            results = fetch_all(catalog, store, client=client)

        assert [r.asset_id for r in results] == ["a", "b"]
        assert all(r.glb.ok for r in results)


class TestFormatSummary:
    def test_renders_success_and_skip(self) -> None:
        store_path_unused = None  # noqa: F841
        # Build a result by hand to keep the test independent of fetch
        # behaviour.
        from ai_edit.pipeline.catalog_fetch import FetchOutcome, FetchResult

        results = [
            FetchResult(
                asset_id="box",
                glb=FetchOutcome(bytes_written=1700),
                usdz=FetchOutcome(skipped_reason="no usdz_url in catalog"),
            ),
            FetchResult(
                asset_id="duck",
                glb=FetchOutcome(error="HTTPStatusError: 404"),
                usdz=FetchOutcome(skipped_reason="no usdz_url in catalog"),
            ),
        ]
        out = format_summary(results)
        assert "box" in out
        assert "duck" in out
        assert "✓ GLB" in out
        assert "✗ GLB" in out
        assert "1.7 KB" in out

    def test_empty_results(self) -> None:
        assert format_summary([]) == "(no entries selected)"
