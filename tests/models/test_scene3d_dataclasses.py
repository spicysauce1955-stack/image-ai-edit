"""Unit tests for the Scene3D capability dataclasses + ABCs.

Phase 0 of the AR plan. No providers, no network — just the shape and
behaviour of :class:`Scene3DAsset`, :class:`Scene3DResponse`,
:class:`Scene3DModel`, and :class:`Format3DConverter`.
"""

from __future__ import annotations

import inspect

import pytest

from ai_edit.models import (
    MIME_GLB,
    MIME_GLTF_JSON,
    MIME_USDZ,
    Format3DConverter,
    Scene3DAsset,
    Scene3DModel,
    Scene3DResponse,
)


class TestScene3DAsset:
    def test_construction_requires_data_mime_extension(self) -> None:
        asset = Scene3DAsset(data=b"GLB\x02...", mime_type=MIME_GLB, extension=".glb")
        assert asset.data == b"GLB\x02..."
        assert asset.mime_type == MIME_GLB
        assert asset.extension == ".glb"
        assert asset.raw == {}

    def test_raw_defaults_to_empty_dict_each_instance(self) -> None:
        # Regression guard: dataclasses with mutable defaults are a
        # classic footgun. ``field(default_factory=dict)`` is what gives
        # us a fresh dict per instance — verify two assets don't share.
        a = Scene3DAsset(data=b"", mime_type=MIME_GLB, extension=".glb")
        b = Scene3DAsset(data=b"", mime_type=MIME_GLB, extension=".glb")
        a.raw["leak"] = True
        assert "leak" not in b.raw

    def test_raw_can_carry_vendor_extras(self) -> None:
        asset = Scene3DAsset(
            data=b"",
            mime_type=MIME_GLB,
            extension=".glb",
            raw={"vendor_id": "meshy-123", "polycount": 4096},
        )
        assert asset.raw["vendor_id"] == "meshy-123"
        assert asset.raw["polycount"] == 4096


class TestScene3DResponse:
    def test_defaults_are_empty(self) -> None:
        response = Scene3DResponse()
        assert response.assets == []
        assert response.text == ""
        assert response.raw == {}

    def test_find_returns_matching_asset(self) -> None:
        glb = Scene3DAsset(data=b"glb", mime_type=MIME_GLB, extension=".glb")
        usdz = Scene3DAsset(data=b"usdz", mime_type=MIME_USDZ, extension=".usdz")
        response = Scene3DResponse(assets=[glb, usdz])

        assert response.find(MIME_GLB) is glb
        assert response.find(MIME_USDZ) is usdz

    def test_find_returns_none_when_missing(self) -> None:
        response = Scene3DResponse(
            assets=[Scene3DAsset(data=b"glb", mime_type=MIME_GLB, extension=".glb")]
        )
        assert response.find(MIME_USDZ) is None

    def test_find_is_case_sensitive(self) -> None:
        # MIME comparison is case-sensitive in our impl — documents the
        # contract so any future "be lenient" PR has to update the test
        # too.
        glb = Scene3DAsset(data=b"glb", mime_type=MIME_GLB, extension=".glb")
        response = Scene3DResponse(assets=[glb])
        assert response.find(MIME_GLB.upper()) is None

    def test_find_returns_first_when_duplicates(self) -> None:
        first = Scene3DAsset(data=b"a", mime_type=MIME_GLB, extension=".glb")
        second = Scene3DAsset(data=b"b", mime_type=MIME_GLB, extension=".glb")
        response = Scene3DResponse(assets=[first, second])
        assert response.find(MIME_GLB) is first

    def test_find_distinguishes_glb_from_gltf_json(self) -> None:
        # Both are "glTF" but they're different containers — clients
        # need to know which they got. Verify ``find`` doesn't smear
        # them together.
        glb = Scene3DAsset(data=b"glb", mime_type=MIME_GLB, extension=".glb")
        gltf = Scene3DAsset(data=b"{}", mime_type=MIME_GLTF_JSON, extension=".gltf")
        response = Scene3DResponse(assets=[glb, gltf])
        assert response.find(MIME_GLB) is glb
        assert response.find(MIME_GLTF_JSON) is gltf


class TestScene3DModelABC:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            Scene3DModel()  # type: ignore[abstract]

    def test_concrete_subclass_works(self) -> None:
        class FakeGenerator(Scene3DModel):
            async def generate(
                self,
                prompt,
                references=None,
                *,
                model=None,
                target_format="glb",
                **kwargs,
            ):
                return Scene3DResponse(
                    assets=[Scene3DAsset(data=b"fake", mime_type=MIME_GLB, extension=".glb")]
                )

        gen = FakeGenerator()
        assert inspect.iscoroutinefunction(gen.generate)


class TestFormat3DConverterABC:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            Format3DConverter()  # type: ignore[abstract]

    def test_concrete_subclass_works(self) -> None:
        class FakeConverter(Format3DConverter):
            async def convert(self, source, target_format, **kwargs):
                return Scene3DAsset(
                    data=source.data, mime_type=MIME_USDZ, extension=".usdz"
                )

        conv = FakeConverter()
        assert inspect.iscoroutinefunction(conv.convert)


class TestMimeConstants:
    def test_constants_have_expected_strings(self) -> None:
        # If anyone changes the literal string, the AR server's
        # response headers and `<model-viewer>` handoff will silently
        # break on real phones. Lock the values in.
        assert MIME_GLB == "model/gltf-binary"
        assert MIME_GLTF_JSON == "model/gltf+json"
        assert MIME_USDZ == "model/vnd.usdz+zip"
