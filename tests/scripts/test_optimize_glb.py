"""Unit tests for the GLB optimizer's pure logic.

The full pipeline depends on the gltf-transform Node CLI (decimation),
so it's not unit-tested here — that's manual / network territory. The
stand-upright rotation is pure geometry and worth pinning down.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")

# scripts/ isn't a package — load by path.
_PATH = Path(__file__).resolve().parents[2] / "scripts" / "optimize_glb.py"
_spec = importlib.util.spec_from_file_location("optimize_glb", _PATH)
assert _spec and _spec.loader
optimize_glb = importlib.util.module_from_spec(_spec)
sys.modules["optimize_glb"] = optimize_glb
_spec.loader.exec_module(optimize_glb)


def _flat_box(x: float, y: float, z: float) -> "trimesh.Trimesh":
    """A box of the given extents, centred at origin."""
    return trimesh.creation.box(extents=(x, y, z))


class TestStandUpright:
    def test_flat_panel_thin_on_Y_is_tipped_up(self) -> None:
        # Lying flat: thin axis is Y (like a fresh Hunyuan3D fence).
        mesh = _flat_box(1.0, 0.05, 0.7)
        optimize_glb._stand_upright(mesh)
        ex = mesh.extents
        # After: thinnest axis should now be Z (depth), not Y.
        assert int(np.argmin(ex)) == 2
        # Tall axis (was Z=0.7) is now Y.
        assert ex[1] == pytest.approx(0.7, abs=1e-6)
        assert ex[2] == pytest.approx(0.05, abs=1e-6)

    def test_sits_on_ground(self) -> None:
        mesh = _flat_box(1.0, 0.05, 0.7)
        optimize_glb._stand_upright(mesh)
        # min Y should be ~0 (resting on the ground plane).
        assert mesh.bounds[0][1] == pytest.approx(0.0, abs=1e-6)

    def test_centred_horizontally(self) -> None:
        mesh = _flat_box(1.0, 0.05, 0.7)
        optimize_glb._stand_upright(mesh)
        lo, hi = mesh.bounds
        assert (lo[0] + hi[0]) / 2 == pytest.approx(0.0, abs=1e-6)
        assert (lo[2] + hi[2]) / 2 == pytest.approx(0.0, abs=1e-6)

    def test_already_upright_panel_left_standing(self) -> None:
        # Thin axis already Z → no rotation; still grounded/centred.
        mesh = _flat_box(1.0, 0.7, 0.05)
        optimize_glb._stand_upright(mesh)
        ex = mesh.extents
        assert int(np.argmin(ex)) == 2  # still thin on Z
        assert mesh.bounds[0][1] == pytest.approx(0.0, abs=1e-6)
