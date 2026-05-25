"""Integration tests for the fence routes (Phase 8.C).

Covers ``POST /api/fence/layout`` (shape, counts, error mapping) and the
``GET /ar/{base}/fence`` WebXR assembly page (component-existence 404 +
HTML wiring). Offline: a tmp_path store seeded with synthetic component
bytes — the layout endpoint is pure geometry and the page only needs the
components to *exist*, not to be valid GLBs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_edit.models import MIME_GLB, Scene3DAsset
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.server.app import create_app


@pytest.fixture
def store(tmp_path: Path) -> FilesystemARStore:
    return FilesystemARStore(tmp_path)


@pytest.fixture
def client(store: FilesystemARStore) -> TestClient:
    return TestClient(create_app(ar_store=store))


def _seed_components(store: FilesystemARStore, base: str) -> None:
    for suffix in ("__panel", "__post"):
        store.put(
            f"{base}{suffix}",
            Scene3DAsset(data=b"GLB\x02fake", mime_type=MIME_GLB, extension=".glb"),
        )


def _spec(path, **kw) -> dict:
    spec = {
        "panel": {"asset_id": "fence__panel", "nominal_width": 2.0},
        "post": {"asset_id": "fence__post", "nominal_width": 0.1},
        "path": path,
    }
    spec.update(kw)
    return spec


class TestLayoutApi:
    def test_straight_run_counts_and_shape(self, client: TestClient) -> None:
        r = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [6, 0, 0]]))
        assert r.status_code == 200
        body = r.json()
        # 6m / 2m nominal → 3 panels, 4 posts (the fencepost rule).
        assert body["counts"] == {"posts": 4, "panels": 3}
        assert len(body["posts"]) == 4 and len(body["panels"]) == 3
        assert body["within_tolerance"] is True
        post = body["posts"][0]
        assert set(post) == {"position", "rotation", "scale", "kind"}
        assert len(post["position"]) == 3 and len(post["rotation"]) == 4
        panel = body["panels"][0]
        assert {"bay_length", "stretch", "step_height"} <= set(panel)

    def test_two_sections_three_posts_not_four(self, client: TestClient) -> None:
        body = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [4, 0, 0]])).json()
        assert body["counts"] == {"posts": 3, "panels": 2}

    def test_posts_evenly_spaced(self, client: TestClient) -> None:
        body = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [6, 0, 0]])).json()
        xs = [p["position"][0] for p in body["posts"]]
        assert xs == pytest.approx([0.0, 2.0, 4.0, 6.0])

    def test_terminal_end_posts(self, client: TestClient) -> None:
        body = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [6, 0, 0]])).json()
        kinds = [p["kind"] for p in body["posts"]]
        assert kinds[0] == "terminal" and kinds[-1] == "terminal"
        assert all(k == "line" for k in kinds[1:-1])

    def test_awkward_length_flags_not_within_tolerance(self, client: TestClient) -> None:
        body = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [3, 0, 0]])).json()
        assert body["within_tolerance"] is False


class TestLayoutApiErrors:
    def test_zero_length_segment_400(self, client: TestClient) -> None:
        r = client.post("/api/fence/layout", json=_spec([[1, 0, 1], [1, 5, 1]]))
        assert r.status_code == 400
        assert "zero-length" in r.json()["detail"]

    def test_polyline_501(self, client: TestClient) -> None:
        r = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [4, 0, 0], [4, 0, 4]]))
        assert r.status_code == 501
        assert "8.D" in r.json()["detail"]

    def test_closed_loop_501(self, client: TestClient) -> None:
        r = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [4, 0, 0]], closed=True))
        assert r.status_code == 501

    def test_unsupported_fit_501(self, client: TestClient) -> None:
        r = client.post("/api/fence/layout", json=_spec([[0, 0, 0], [4, 0, 0]], fit="tile"))
        assert r.status_code == 501

    def test_too_few_points_422(self, client: TestClient) -> None:
        # Pydantic rejects path with < 2 points before the engine runs.
        r = client.post("/api/fence/layout", json=_spec([[0, 0, 0]]))
        assert r.status_code == 422

    def test_nonpositive_width_422(self, client: TestClient) -> None:
        spec = _spec([[0, 0, 0], [4, 0, 0]])
        spec["panel"]["nominal_width"] = 0.0
        r = client.post("/api/fence/layout", json=spec)
        assert r.status_code == 422


class TestFencePage:
    def test_renders_when_components_exist(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        _seed_components(store, "fence")
        r = client.get("/ar/fence/fence")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        body = r.text
        # WebXR scaffold + the assembly wiring.
        assert "three.module.js" in body
        assert "ARButton" in body
        assert "hit-test" in body
        assert "InstancedMesh" in body
        # Calls the layout API rather than re-implementing geometry.
        assert "/api/fence/layout" in body
        # Loads both component GLBs by id.
        assert '"fence__panel"' in body
        assert '"fence__post"' in body
        assert "/ar/fence__panel/model.glb" in body or "modelUrlFor" in body

    def test_404_when_components_missing(self, client: TestClient) -> None:
        r = client.get("/ar/ghost/fence")
        assert r.status_code == 404

    def test_404_when_only_panel_present(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        store.put(
            "half__panel",
            Scene3DAsset(data=b"GLB\x02fake", mime_type=MIME_GLB, extension=".glb"),
        )
        r = client.get("/ar/half/fence")
        assert r.status_code == 404

    def test_invalid_base_id_rejected(self, client: TestClient) -> None:
        r = client.get("/ar/has%20space/fence")
        assert r.status_code in (404, 422)


class TestExistingRoutesIntact:
    """Phase 8.C is additive — the /ar viewer + live routes still work."""

    def test_live_route_unaffected(
        self, store: FilesystemARStore, client: TestClient
    ) -> None:
        store.put(
            "demo",
            Scene3DAsset(data=b"GLB\x02fake", mime_type=MIME_GLB, extension=".glb"),
        )
        assert client.get("/ar/demo/live").status_code == 200
        assert client.get("/ar/demo").status_code == 200
