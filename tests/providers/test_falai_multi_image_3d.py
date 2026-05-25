"""Unit tests for FalAIMultiImageTo3D (Phase 7.A).

All fal calls are mocked — no network, no cost. ``fal_client.subscribe``
is patched on the real module (the handler does ``import fal_client``
inside the method, which resolves to the same cached module object), and
the module-level ``_download`` is patched to skip the HTTP fetch.

A live, cost-incurring integration test is intentionally NOT here — that
belongs behind ``RUN_NETWORK_TESTS=1`` and is added when we want to
validate real output (Phase 7.B manual pass / a gated test).
"""

from __future__ import annotations

import fal_client
import pytest

import ai_edit.providers.falai as falai_mod
from ai_edit.models import MIME_GLB, Scene3DResponse
from ai_edit.providers.falai import FalAI, FalAIMultiImageTo3D, _first_model_url


@pytest.fixture
def provider() -> FalAI:
    # api_key arg avoids any dependency on FAL_KEY in the environment.
    return FalAI(api_key="test-key")


@pytest.fixture
def fake_fal(monkeypatch: pytest.MonkeyPatch):
    """Patch fal_client.subscribe + _download; capture the call args."""
    captured: dict = {}

    def fake_subscribe(model_id, *, arguments, with_logs=False):
        captured["model_id"] = model_id
        captured["arguments"] = arguments
        captured["with_logs"] = with_logs
        return {"model_glb": {"url": "https://fal.invalid/model.glb"}}

    async def fake_download(url, **kwargs):
        captured["downloaded_url"] = url
        return b"GLB-BYTES"

    monkeypatch.setattr(fal_client, "subscribe", fake_subscribe)
    monkeypatch.setattr(falai_mod, "_download", fake_download)
    return captured


def _img(tag: bytes) -> tuple[bytes, str]:
    return (tag, "image/jpeg")


class TestFirstModelUrl:
    def test_reads_model_glb_url(self) -> None:
        assert (
            _first_model_url({"model_glb": {"url": "https://x/m.glb"}})
            == "https://x/m.glb"
        )

    def test_falls_back_to_model_urls_glb(self) -> None:
        data = {"model_urls": {"glb": {"url": "https://x/alt.glb"}}}
        assert _first_model_url(data) == "https://x/alt.glb"

    def test_raises_when_no_glb(self) -> None:
        with pytest.raises(RuntimeError, match="no GLB"):
            _first_model_url({"thumbnail": {"url": "https://x/p.png"}})


class TestGenerate:
    async def test_single_front_image(self, provider: FalAI, fake_fal) -> None:
        resp = await provider.multi_image_3d.generate(
            "ignored prompt", references=[_img(b"front")]
        )
        assert isinstance(resp, Scene3DResponse)
        asset = resp.find(MIME_GLB)
        assert asset is not None
        assert asset.data == b"GLB-BYTES"
        assert asset.extension == ".glb"
        # Only the front slot is populated.
        args = fake_fal["arguments"]
        assert "front_image_url" in args
        assert "back_image_url" not in args
        assert fake_fal["model_id"] == "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d"

    async def test_four_views_map_to_named_slots_in_order(
        self, provider: FalAI, fake_fal
    ) -> None:
        await provider.multi_image_3d.generate(
            "",
            references=[_img(b"F"), _img(b"B"), _img(b"L"), _img(b"R")],
        )
        args = fake_fal["arguments"]
        # Each slot carries a data URI of the corresponding image.
        import base64

        def b64(tag: bytes) -> str:
            return base64.b64encode(tag).decode()

        assert b64(b"F") in args["front_image_url"]
        assert b64(b"B") in args["back_image_url"]
        assert b64(b"L") in args["left_image_url"]
        assert b64(b"R") in args["right_image_url"]

    async def test_no_references_raises(self, provider: FalAI, fake_fal) -> None:
        with pytest.raises(ValueError, match="at least one reference"):
            await provider.multi_image_3d.generate("x", references=None)
        with pytest.raises(ValueError, match="at least one reference"):
            await provider.multi_image_3d.generate("x", references=[])

    async def test_extra_references_beyond_cardinals_ignored(
        self, provider: FalAI, fake_fal
    ) -> None:
        # 5 images, only 4 cardinal slots exist → 5th is dropped (unless
        # the caller passes an explicit extra slot via kwargs).
        await provider.multi_image_3d.generate(
            "",
            references=[_img(b"F"), _img(b"B"), _img(b"L"), _img(b"R"), _img(b"X")],
        )
        args = fake_fal["arguments"]
        slots = [k for k in args if k.endswith("_image_url")]
        assert len(slots) == 4

    async def test_kwargs_forwarded(self, provider: FalAI, fake_fal) -> None:
        await provider.multi_image_3d.generate(
            "",
            references=[_img(b"front")],
            enable_pbr=True,
            generate_type="Normal",
            face_count=200000,
        )
        args = fake_fal["arguments"]
        assert args["enable_pbr"] is True
        assert args["generate_type"] == "Normal"
        assert args["face_count"] == 200000

    async def test_model_override(self, provider: FalAI, fake_fal) -> None:
        await provider.multi_image_3d.generate(
            "", references=[_img(b"front")], model="fal-ai/some/other-model"
        )
        assert fake_fal["model_id"] == "fal-ai/some/other-model"

    async def test_raw_preserved(self, provider: FalAI, fake_fal) -> None:
        resp = await provider.multi_image_3d.generate("", references=[_img(b"f")])
        assert resp.raw == {"model_glb": {"url": "https://fal.invalid/model.glb"}}
        assert resp.assets[0].raw == resp.raw


class TestRegistration:
    def test_provider_exposes_handler(self, provider: FalAI) -> None:
        assert isinstance(provider.multi_image_3d, FalAIMultiImageTo3D)
