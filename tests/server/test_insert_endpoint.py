"""Regression tests for the image insertion HTTP endpoint.

These stay offline by monkeypatching the provider-backed pipeline call.
The goal is to lock down request validation, temporary-file handling,
and result-token semantics at the FastAPI boundary.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import ai_edit.server.app as app_module
from ai_edit.pipeline.insert import InsertResult
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.server.app import create_app


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def clear_result_cache() -> None:
    app_module._RESULT_CACHE.clear()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    store = FilesystemARStore(tmp_path / "ar")
    return TestClient(create_app(ar_store=store))


def _files(
    *,
    scene_name: str = "scene.png",
    reference_name: str = "reference.png",
) -> dict[str, tuple[str, bytes, str]]:
    return {
        "scene": (scene_name, _png_bytes(), "image/png"),
        "reference": (reference_name, _png_bytes(), "image/png"),
    }


def test_upload_filenames_do_not_control_temp_paths(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    seen: dict[str, Path] = {}

    async def fake_insert(scene_path, reference_path, instruction, **kwargs):
        seen["scene"] = Path(scene_path)
        seen["reference"] = Path(reference_path)
        return InsertResult(composite_bytes=_png_bytes(), composite_mime="image/png")

    monkeypatch.setattr(app_module, "insert_object", fake_insert)

    r = client.post(
        "/api/insert",
        data={"instruction": "place it", "mode": "free"},
        files=_files(scene_name="/tmp/escape.png", reference_name="../reference.png"),
    )

    assert r.status_code == 200
    assert seen["scene"].name == "scene.png"
    assert seen["reference"].name == "reference.png"
    assert seen["scene"].parent == seen["reference"].parent


def test_bad_pole_coordinates_return_400(client: TestClient) -> None:
    r = client.post(
        "/api/insert",
        data={
            "instruction": "place it",
            "mode": "mask",
            "poles": '[["x", 0.5], [0.75, 0.5]]',
        },
        files=_files(),
    )

    assert r.status_code == 400
    assert "Bad poles vertex" in r.text


def test_invalid_images_return_400(client: TestClient) -> None:
    r = client.post(
        "/api/insert",
        data={"instruction": "place it", "mode": "free"},
        files={
            "scene": ("scene.png", b"not an image", "image/png"),
            "reference": ("reference.png", _png_bytes(), "image/png"),
        },
    )

    assert r.status_code == 400
    assert "scene must be a valid image" in r.text


def test_result_urls_are_one_shot_but_aux_survives_composite_fetch(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    async def fake_insert(scene_path, reference_path, instruction, **kwargs):
        return InsertResult(
            composite_bytes=_png_bytes(),
            composite_mime="image/png",
            aux_bytes=_png_bytes(),
            aux_kind="mask",
        )

    monkeypatch.setattr(app_module, "insert_object", fake_insert)

    created = client.post(
        "/api/insert",
        data={"instruction": "place it", "mode": "free"},
        files=_files(),
    )

    assert created.status_code == 200
    payload = created.json()

    first_composite = client.get(payload["composite_url"])
    second_composite = client.get(payload["composite_url"])
    first_aux = client.get(payload["aux_url"])
    second_aux = client.get(payload["aux_url"])

    assert first_composite.status_code == 200
    assert second_composite.status_code == 404
    assert first_aux.status_code == 200
    assert second_aux.status_code == 404
