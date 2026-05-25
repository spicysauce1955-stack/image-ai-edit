"""Unit tests for the fence component builder (Phase 8.B).

All fal calls are faked (no network) and optimization is disabled (no
Node). A real trimesh box GLB stands in for the generated mesh so
measure_nominal_width and validate_glb exercise real code.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

trimesh = pytest.importorskip("trimesh")

from ai_edit.models import MIME_GLB, Scene3DAsset, Scene3DResponse
from ai_edit.pipeline.ar_store import FilesystemARStore
from ai_edit.pipeline import fence_components as fc


def _box_glb(width=2.0, height=0.7, depth=0.05) -> bytes:
    return trimesh.creation.box(extents=(width, height, depth)).export(file_type="glb")


def _png(color=(128, 128, 128)) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


class _FakeNano:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def edit(self, scene, references, prompt, **kw):
        self.prompts.append(prompt)
        return SimpleNamespace(image_bytes=_png())


class _Fake3D:
    def __init__(self, glb: bytes) -> None:
        self.glb = glb
        self.calls: list[int] = []

    async def generate(self, prompt, references=None, **kw):
        self.calls.append(len(references or []))
        return Scene3DResponse(
            assets=[Scene3DAsset(data=self.glb, mime_type=MIME_GLB, extension=".glb")]
        )


class _FakeFal:
    def __init__(self, glb: bytes) -> None:
        self.nano_banana = _FakeNano()
        self.multi_image_3d = _Fake3D(glb)


class TestMeasureNominalWidth:
    def test_returns_x_extent(self) -> None:
        assert fc.measure_nominal_width(_box_glb(2.0, 0.7, 0.05)) == pytest.approx(2.0)

    def test_post_thin(self) -> None:
        assert fc.measure_nominal_width(_box_glb(0.1, 1.5, 0.1)) == pytest.approx(0.1)


class TestComponentIds:
    def test_ids(self) -> None:
        assert fc.panel_component_id("fence") == "fence__panel"
        assert fc.post_component_id("fence") == "fence__post"


class TestMakeViews:
    async def test_single_view_when_not_multiview(self) -> None:
        fal = _FakeFal(_box_glb())
        views = await fc._make_views(fal, _png(), multiview=False)
        assert len(views) == 1
        assert fal.nano_banana.prompts == []  # no extra generations

    async def test_multiview_makes_four_with_mirrored_right(self) -> None:
        fal = _FakeFal(_box_glb())
        front = _png((10, 20, 30))
        views = await fc._make_views(fal, front, multiview=True)
        assert len(views) == 4  # front, back, left, right
        assert views[0][0] == front
        # right (index 3) is the horizontal mirror of left (index 2)
        from PIL import Image, ImageChops

        left = Image.open(BytesIO(views[2][0]))
        right = Image.open(BytesIO(views[3][0]))
        remirror = right.transpose(Image.FLIP_LEFT_RIGHT)
        assert ImageChops.difference(left.convert("RGB"), remirror.convert("RGB")).getbbox() is None
        # two real generations: back + one side
        assert len(fal.nano_banana.prompts) == 2


class TestBuildComponent:
    async def test_builds_stores_and_measures(self, tmp_path: Path) -> None:
        fal = _FakeFal(_box_glb(2.0, 0.7, 0.05))
        store = FilesystemARStore(tmp_path)
        ref = await fc.build_component(
            fal=fal,
            store=store,
            source_image=(_png(), "image/png"),
            component_id="fence__panel",
            isolate_prompt=fc.PANEL_ISOLATE_PROMPT,
            multiview=True,
            optimize=False,
        )
        assert ref.asset_id == "fence__panel"
        assert ref.nominal_width == pytest.approx(2.0)
        # stored + retrievable
        assert store.get("fence__panel", MIME_GLB) is not None
        # multiview path fed 4 views to the 3D model
        assert fal.multi_image_3d.calls == [4]

    async def test_post_single_view(self, tmp_path: Path) -> None:
        fal = _FakeFal(_box_glb(0.1, 1.5, 0.1))
        store = FilesystemARStore(tmp_path)
        ref = await fc.build_component(
            fal=fal,
            store=store,
            source_image=(_png(), "image/png"),
            component_id="fence__post",
            isolate_prompt=fc.POST_ISOLATE_PROMPT,
            multiview=False,
            optimize=False,
        )
        assert ref.nominal_width == pytest.approx(0.1)
        assert fal.multi_image_3d.calls == [1]  # single view


class TestBuildFenceComponents:
    async def test_builds_both(self, tmp_path: Path) -> None:
        fal = _FakeFal(_box_glb(2.0, 0.7, 0.05))
        store = FilesystemARStore(tmp_path)
        comps = await fc.build_fence_components(
            fal=fal,
            store=store,
            source_image=(_png(), "image/png"),
            base_id="myfence",
            optimize=False,
        )
        assert comps.panel.asset_id == "myfence__panel"
        assert comps.post.asset_id == "myfence__post"
        assert store.get("myfence__panel", MIME_GLB) is not None
        assert store.get("myfence__post", MIME_GLB) is not None
        # panel multiview (4) then post single (1)
        assert fal.multi_image_3d.calls == [4, 1]
