"""Unit tests for ARStore and FilesystemARStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_edit.models import MIME_GLB, MIME_GLTF_JSON, MIME_USDZ, Scene3DAsset
from ai_edit.pipeline.ar_store import (
    ARStore,
    FilesystemARStore,
    filename_for_mime,
    validate_scene_id,
)


class TestFilenameForMime:
    def test_known_mimes(self) -> None:
        assert filename_for_mime(MIME_GLB) == "model.glb"
        assert filename_for_mime(MIME_USDZ) == "model.usdz"
        assert filename_for_mime(MIME_GLTF_JSON) == "model.gltf"

    def test_unknown_mime_returns_none(self) -> None:
        assert filename_for_mime("application/json") is None
        assert filename_for_mime("") is None


class TestValidateSceneId:
    def test_allows_expected_url_safe_ids(self) -> None:
        validate_scene_id("scene_42-A")

    @pytest.mark.parametrize("scene_id", ["", "../escape", "has space", "a" * 65])
    def test_rejects_unsafe_ids(self, scene_id: str) -> None:
        with pytest.raises(ValueError, match="scene_id"):
            validate_scene_id(scene_id)


class TestARStoreABC:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            ARStore()  # type: ignore[abstract]


class TestFilesystemARStore:
    def test_exists_false_for_missing_scene(self, tmp_path: Path) -> None:
        store = FilesystemARStore(tmp_path)
        assert store.exists("anything") is False

    def test_exists_false_for_empty_scene_dir(self, tmp_path: Path) -> None:
        # An empty directory should not count as "exists" — without
        # this, a bug elsewhere could create empty scene dirs and
        # turn 404s into 500s when the route tries to load bytes.
        store = FilesystemARStore(tmp_path)
        (tmp_path / "scene_a").mkdir()
        assert store.exists("scene_a") is False

    def test_put_then_get_roundtrip_glb(self, tmp_path: Path) -> None:
        store = FilesystemARStore(tmp_path)
        asset = Scene3DAsset(data=b"glb-bytes-here", mime_type=MIME_GLB, extension=".glb")
        store.put("scene_a", asset)
        assert store.exists("scene_a") is True
        assert store.get("scene_a", MIME_GLB) == b"glb-bytes-here"

    def test_put_then_get_roundtrip_usdz(self, tmp_path: Path) -> None:
        store = FilesystemARStore(tmp_path)
        asset = Scene3DAsset(data=b"usdz-bytes", mime_type=MIME_USDZ, extension=".usdz")
        store.put("scene_b", asset)
        assert store.get("scene_b", MIME_USDZ) == b"usdz-bytes"

    def test_put_creates_parent_dirs(self, tmp_path: Path) -> None:
        # Deliberately point the store at a not-yet-existing root to
        # verify lazy creation works.
        nested = tmp_path / "deep" / "scenes"
        store = FilesystemARStore(nested)
        store.put(
            "scene_c",
            Scene3DAsset(data=b"x", mime_type=MIME_GLB, extension=".glb"),
        )
        assert (nested / "scene_c" / "model.glb").is_file()

    def test_get_returns_none_for_missing_scene(self, tmp_path: Path) -> None:
        store = FilesystemARStore(tmp_path)
        assert store.get("nope", MIME_GLB) is None

    def test_get_returns_none_for_missing_format(self, tmp_path: Path) -> None:
        store = FilesystemARStore(tmp_path)
        store.put(
            "scene_d",
            Scene3DAsset(data=b"glb", mime_type=MIME_GLB, extension=".glb"),
        )
        # GLB present, USDZ absent — must distinguish.
        assert store.get("scene_d", MIME_GLB) == b"glb"
        assert store.get("scene_d", MIME_USDZ) is None

    def test_get_unknown_mime_returns_none_not_raises(self, tmp_path: Path) -> None:
        # The route layer relies on None-for-unknown so it can return
        # a clean 404 without a try/except around every call.
        store = FilesystemARStore(tmp_path)
        assert store.get("anything", "image/png") is None

    def test_put_unknown_mime_raises(self, tmp_path: Path) -> None:
        # Symmetrically — *writing* an unknown MIME is a bug, not a
        # silently-dropped asset.
        store = FilesystemARStore(tmp_path)
        bogus = Scene3DAsset(data=b"x", mime_type="image/png", extension=".png")
        with pytest.raises(ValueError, match="unsupported MIME"):
            store.put("scene_e", bogus)

    def test_put_overwrites_silently(self, tmp_path: Path) -> None:
        store = FilesystemARStore(tmp_path)
        first = Scene3DAsset(data=b"v1", mime_type=MIME_GLB, extension=".glb")
        second = Scene3DAsset(data=b"v2", mime_type=MIME_GLB, extension=".glb")
        store.put("scene_f", first)
        store.put("scene_f", second)
        assert store.get("scene_f", MIME_GLB) == b"v2"

    def test_str_path_argument(self, tmp_path: Path) -> None:
        # The constructor accepts ``str | Path`` — verify the str path
        # works as well as the Path path.
        store = FilesystemARStore(str(tmp_path))
        store.put(
            "scene_g",
            Scene3DAsset(data=b"x", mime_type=MIME_GLB, extension=".glb"),
        )
        assert store.exists("scene_g") is True

    def test_rejects_path_traversal_scene_id(self, tmp_path: Path) -> None:
        store = FilesystemARStore(tmp_path)
        asset = Scene3DAsset(data=b"x", mime_type=MIME_GLB, extension=".glb")
        with pytest.raises(ValueError, match="scene_id"):
            store.put("../escape", asset)
        assert not (tmp_path.parent / "escape").exists()
