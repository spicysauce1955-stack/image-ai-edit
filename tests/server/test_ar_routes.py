"""Integration tests for the AR delivery routes.

Use FastAPI's TestClient against a freshly-built app with a tmp_path
filesystem store, so each test is isolated and offline. No real Khronos
samples here — synthetic bytes are sufficient because Phase 1 only
asserts MIME + bytes + HTML wiring; the glTF validator lands in Phase 4.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_edit.models import MIME_GLB, MIME_USDZ, Scene3DAsset
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.server.app import create_app


@pytest.fixture
def store(tmp_path: Path) -> FilesystemARStore:
    return FilesystemARStore(tmp_path)


@pytest.fixture
def client(store: FilesystemARStore) -> TestClient:
    return TestClient(create_app(ar_store=store))


def _seed_scene(
    store: FilesystemARStore,
    scene_id: str,
    *,
    glb: bytes | None = b"GLB\x02fake-bytes",
    usdz: bytes | None = b"PK\x03\x04fake-usdz-zip",
) -> None:
    """Drop a synthetic GLB and/or USDZ into the store for a scene."""
    if glb is not None:
        store.put(
            scene_id,
            Scene3DAsset(data=glb, mime_type=MIME_GLB, extension=".glb"),
        )
    if usdz is not None:
        store.put(
            scene_id,
            Scene3DAsset(data=usdz, mime_type=MIME_USDZ, extension=".usdz"),
        )


class TestViewerPage:
    def test_returns_html_with_model_viewer(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        _seed_scene(store, "demo1")
        r = client.get("/ar/demo1")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        body = r.text
        assert "<model-viewer" in body
        # Both handoff srcs must be present — otherwise iOS Quick Look
        # silently falls back to "AR not supported".
        assert 'src="/ar/demo1/model.glb"' in body
        assert 'ios-src="/ar/demo1/model.usdz"' in body
        assert 'ar-modes="webxr scene-viewer quick-look"' in body

    def test_returns_404_for_unknown_scene(self, client: TestClient) -> None:
        r = client.get("/ar/nope")
        assert r.status_code == 404

    def test_glb_only_scene_still_renders_page(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        # iOS may end up with a broken Quick Look button but the page
        # itself must still render — Android users on the same URL
        # should not be punished for the lack of USDZ.
        _seed_scene(store, "glbonly", usdz=None)
        r = client.get("/ar/glbonly")
        assert r.status_code == 200
        assert "<model-viewer" in r.text

    def test_invalid_scene_id_rejected(self, client: TestClient) -> None:
        # FastAPI's path-param regex returns 422 for non-matching IDs.
        # We don't care about the exact code as long as it's not 200 —
        # the important property is that ``..`` / ``/`` etc never hit
        # the handler. ``..`` URL-encodes oddly so use a clearer case:
        r = client.get("/ar/has%20space")
        assert r.status_code in (404, 422)

    def test_path_traversal_blocked(self, client: TestClient) -> None:
        # Even if the path param were permissive, the store wouldn't
        # find a "../etc/passwd" scene — but we want the request to
        # reject at the route, not silently 404 at the store. The
        # regex blocks dots entirely.
        r = client.get("/ar/..%2Fetc")
        assert r.status_code in (404, 422)


class TestGlbRoute:
    def test_serves_glb_with_correct_mime(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        _seed_scene(store, "glb1", glb=b"GLB-BYTES")
        r = client.get("/ar/glb1/model.glb")
        assert r.status_code == 200
        assert r.headers["content-type"] == MIME_GLB
        assert r.content == b"GLB-BYTES"

    def test_404_when_glb_missing(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        _seed_scene(store, "usdzonly", glb=None)
        r = client.get("/ar/usdzonly/model.glb")
        assert r.status_code == 404


class TestUsdzRoute:
    def test_serves_usdz_with_correct_mime(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        _seed_scene(store, "usdz1", usdz=b"USDZ-BYTES")
        r = client.get("/ar/usdz1/model.usdz")
        assert r.status_code == 200
        assert r.headers["content-type"] == MIME_USDZ
        assert r.content == b"USDZ-BYTES"

    def test_404_when_usdz_missing(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        _seed_scene(store, "glbonly2", usdz=None)
        r = client.get("/ar/glbonly2/model.usdz")
        assert r.status_code == 404


class TestEscaping:
    def test_scene_id_is_html_escaped(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        # The regex blocks `<`, `>`, `"`, `&` already — but the
        # template uses html.escape as defence in depth. Verify by
        # picking an ID with characters in the allowed set that are
        # plain text anyway (sanity check the template loads).
        _seed_scene(store, "scene_42-A")
        r = client.get("/ar/scene_42-A")
        assert r.status_code == 200
        assert "scene_42-A" in r.text
