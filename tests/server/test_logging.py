"""Tests for the AR + catalog route logging and the setup helper."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_edit.models import MIME_GLB, Scene3DAsset
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.pipeline.asset_catalog import AssetCatalog, AssetCatalogEntry
from ai_edit.server.app import create_app
from ai_edit.server.logging_setup import setup_logging

from tests.conftest import minimal_glb_bytes


def _catalog() -> AssetCatalog:
    return AssetCatalog(
        [
            AssetCatalogEntry.from_dict(
                {
                    "id": "alpha",
                    "name": "Alpha",
                    "category": "sample",
                    "description": "",
                    "glb_url": "https://example.invalid/x.glb",
                    "usdz_url": None,
                    "thumbnail_url": None,
                    "license": "CC0-1.0",
                    "attribution": "",
                    "source_url": "https://example.invalid",
                    "scale_hint": None,
                }
            )
        ]
    )


class TestSetupLogging:
    def test_returns_named_logger(self) -> None:
        logger = setup_logging()
        assert logger.name == "ai_edit"

    def test_is_idempotent(self) -> None:
        a = setup_logging()
        b = setup_logging()
        assert a is b
        # Adding handlers twice would double every log line — verify
        # we only have one StreamHandler.
        from logging import StreamHandler

        stream_handlers = [h for h in a.handlers if isinstance(h, StreamHandler)]
        assert len(stream_handlers) == 1


class TestArRouteLogs:
    @pytest.fixture
    def store(self, tmp_path: Path) -> FilesystemARStore:
        s = FilesystemARStore(tmp_path)
        s.put(
            "demo",
            Scene3DAsset(data=minimal_glb_bytes(), mime_type=MIME_GLB, extension=".glb"),
        )
        return s

    @pytest.fixture
    def client(self, store: FilesystemARStore) -> TestClient:
        return TestClient(create_app(ar_store=store, catalog=_catalog()))

    def test_200_logs_status_and_bytes(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="ai_edit.ar"):
            r = client.get("/ar/demo/model.glb")
        assert r.status_code == 200
        log_text = "\n".join(rec.message for rec in caplog.records if rec.name == "ai_edit.ar")
        assert "ar.glb" in log_text
        assert "status=200" in log_text
        assert "scene=demo" in log_text
        assert "bytes=" in log_text

    def test_404_logs_status(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="ai_edit.ar"):
            r = client.get("/ar/missing/model.glb")
        assert r.status_code == 404
        log_text = "\n".join(rec.message for rec in caplog.records if rec.name == "ai_edit.ar")
        assert "ar.glb" in log_text
        assert "status=404" in log_text
        assert "scene=missing" in log_text

    def test_viewer_logs_separately_from_asset(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="ai_edit.ar"):
            client.get("/ar/demo")
            client.get("/ar/demo/model.glb")
        messages = [rec.message for rec in caplog.records if rec.name == "ai_edit.ar"]
        # Two distinct events with distinct event names.
        assert any("ar.viewer" in m for m in messages)
        assert any("ar.glb" in m for m in messages)


class TestCatalogRouteLogs:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(create_app(catalog=_catalog()))

    def test_404_get_entry_logged(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="ai_edit.catalog"):
            r = client.get("/api/catalog/missing_id")
        assert r.status_code == 404
        log_text = "\n".join(
            rec.message for rec in caplog.records if rec.name == "ai_edit.catalog"
        )
        assert "catalog.get" in log_text
        assert "status=404" in log_text
        assert "id=missing_id" in log_text
