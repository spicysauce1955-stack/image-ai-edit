"""Unit tests for the fence layout engine (Phase 8.A).

Pure geometry — no AR, no network. Covers the shared-post rule, bay
fitting, stepping, and the level-panel / plumb-post invariants.
"""

from __future__ import annotations

import math

import pytest

from ai_edit.pipeline.fence import (
    ComponentRef,
    FenceSpec,
    compute_fence_layout,
    rotate_vector,
)

PANEL = ComponentRef(asset_id="fence__panel", nominal_width=2.0)
POST = ComponentRef(asset_id="fence__post", nominal_width=0.1)


def _spec(path, **kw) -> FenceSpec:
    return FenceSpec(panel=PANEL, post=POST, path=tuple(path), **kw)


def _approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


class TestSharedPostCount:
    @pytest.mark.parametrize("n_expected,length", [(1, 2.0), (2, 4.0), (5, 10.0), (10, 20.0)])
    def test_open_run_has_n_plus_1_posts(self, n_expected, length):
        layout = compute_fence_layout(_spec([(0, 0, 0), (length, 0, 0)]))
        assert len(layout.panels) == n_expected
        assert len(layout.posts) == n_expected + 1  # the fencepost rule

    def test_single_panel_two_posts(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (2.0, 0, 0)]))
        assert len(layout.panels) == 1
        assert len(layout.posts) == 2

    def test_two_panels_three_posts_not_four(self):
        # The headline example: 2 combined sections → 3 posts, not 4.
        layout = compute_fence_layout(_spec([(0, 0, 0), (4.0, 0, 0)]))
        assert len(layout.panels) == 2
        assert len(layout.posts) == 3


class TestBayFitting:
    def test_exact_multiple_no_stretch(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (6.0, 0, 0)]))  # 3 × 2.0
        assert len(layout.panels) == 3
        assert all(_approx(p.stretch, 1.0) for p in layout.panels)
        assert layout.within_tolerance

    def test_picks_minimal_stretch_count(self):
        # length 5.0, nominal 2.0 → raw 2.5; floor=2 (bay 2.5, err .5),
        # ceil=3 (bay 1.667, err .333) → choose 3.
        layout = compute_fence_layout(_spec([(0, 0, 0), (5.0, 0, 0)]))
        assert len(layout.panels) == 3
        assert _approx(layout.panels[0].bay_length, 5.0 / 3.0)

    def test_within_tolerance_flag_false_for_awkward_length(self):
        # length 3.0, nominal 2.0 → raw 1.5; n=2 bay 1.5 (25% squeeze) or
        # n=1 bay 3.0 (50% stretch) → n=2, |stretch-1|=0.25 > 0.12.
        layout = compute_fence_layout(_spec([(0, 0, 0), (3.0, 0, 0)]))
        assert len(layout.panels) == 2
        assert not layout.within_tolerance

    def test_bay_length_uniform(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (7.0, 0, 0)]))
        bays = {round(p.bay_length, 9) for p in layout.panels}
        assert len(bays) == 1  # all bays equal in a straight run


class TestGeometry:
    def test_posts_evenly_spaced_along_x(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (6.0, 0, 0)]))
        xs = [p.transform.position[0] for p in layout.posts]
        assert xs == pytest.approx([0.0, 2.0, 4.0, 6.0])

    def test_panel_centered_between_its_posts(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (6.0, 0, 0)]))
        for i, panel in enumerate(layout.panels):
            a = layout.posts[i].transform.position
            b = layout.posts[i + 1].transform.position
            assert _approx(panel.transform.position[0], (a[0] + b[0]) / 2)
            assert _approx(panel.transform.position[2], (a[2] + b[2]) / 2)

    def test_end_posts_terminal_middle_posts_line(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (6.0, 0, 0)]))
        kinds = [p.kind for p in layout.posts]
        assert kinds[0] == "terminal" and kinds[-1] == "terminal"
        assert all(k == "line" for k in kinds[1:-1])

    def test_yaw_aligns_width_axis_to_segment(self):
        # Run along +Z: a panel's local +X (width) should rotate to +Z.
        layout = compute_fence_layout(_spec([(0, 0, 0), (0, 0, 6.0)]))
        q = layout.panels[0].transform.rotation
        wx, wy, wz = rotate_vector(q, (1.0, 0.0, 0.0))
        assert _approx(wx, 0.0) and _approx(wy, 0.0) and _approx(wz, 1.0)


class TestInvariants:
    def test_posts_always_plumb_identity_rotation(self):
        layout = compute_fence_layout(_spec([(0, 1, 0), (6.0, 3, 2.0)]))  # sloped + angled
        for post in layout.posts:
            assert post.transform.rotation == (0.0, 0.0, 0.0, 1.0)

    def test_panels_always_level_yaw_only(self):
        # A yaw-only (about +Y) quaternion has x == z == 0.
        layout = compute_fence_layout(_spec([(0, 1, 0), (6.0, 3, 2.0)]))
        for panel in layout.panels:
            qx, qy, qz, qw = panel.transform.rotation
            assert _approx(qx, 0.0) and _approx(qz, 0.0)
            # the panel's up vector stays world-up (level, no pitch/roll)
            ux, uy, uz = rotate_vector(panel.transform.rotation, (0.0, 1.0, 0.0))
            assert _approx(ux, 0.0) and _approx(uy, 1.0) and _approx(uz, 0.0)


class TestStepping:
    def test_posts_plant_at_interpolated_ground_height(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (4.0, 2.0, 0)]))  # rises 2m over 2 bays
        ys = [round(p.transform.position[1], 6) for p in layout.posts]
        assert ys == [0.0, 1.0, 2.0]  # linear ground

    def test_panels_step_at_max_height_by_default(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (4.0, 2.0, 0)]))
        # bay0 between y=0 and y=1 → step 1.0; bay1 between y=1 and y=2 → 2.0
        assert _approx(layout.panels[0].step_height, 1.0)
        assert _approx(layout.panels[1].step_height, 2.0)
        # panel y position == its step height
        assert _approx(layout.panels[0].transform.position[1], 1.0)

    def test_step_rule_min_and_mean(self):
        lo = compute_fence_layout(_spec([(0, 0, 0), (4.0, 2.0, 0)], step_rule="min"))
        assert _approx(lo.panels[0].step_height, 0.0)
        mid = compute_fence_layout(_spec([(0, 0, 0), (4.0, 2.0, 0)], step_rule="mean"))
        assert _approx(mid.panels[0].step_height, 0.5)

    def test_flat_ground_all_equal_step(self):
        layout = compute_fence_layout(_spec([(0, 0, 0), (6.0, 0, 0)]))
        assert all(_approx(p.step_height, 0.0) for p in layout.panels)


class TestErrors:
    def test_too_few_points(self):
        with pytest.raises(ValueError, match="at least 2 points"):
            compute_fence_layout(_spec([(0, 0, 0)]))

    def test_zero_length_segment(self):
        with pytest.raises(ValueError, match="zero-length"):
            compute_fence_layout(_spec([(1, 0, 1), (1, 5, 1)]))  # same XZ

    def test_bad_nominal_width(self):
        spec = FenceSpec(
            panel=ComponentRef("p", 0.0), post=POST, path=((0, 0, 0), (4, 0, 0))
        )
        with pytest.raises(ValueError, match="nominal_width"):
            compute_fence_layout(spec)

    def test_polyline_not_yet_supported(self):
        with pytest.raises(NotImplementedError, match="Phase 8.D"):
            compute_fence_layout(_spec([(0, 0, 0), (4, 0, 0), (4, 0, 4)]))

    def test_closed_not_yet_supported(self):
        with pytest.raises(NotImplementedError, match="Phase 8.D"):
            compute_fence_layout(_spec([(0, 0, 0), (4, 0, 0)], closed=True))

    def test_nonstretch_fit_reserved(self):
        with pytest.raises(NotImplementedError, match="stretch"):
            compute_fence_layout(_spec([(0, 0, 0), (4, 0, 0)], fit="tile"))


class TestDeterminism:
    def test_same_spec_same_layout(self):
        spec = _spec([(0, 0, 0), (7.3, 1.2, 2.1)])
        a = compute_fence_layout(spec)
        b = compute_fence_layout(spec)
        assert a == b


class TestRotateVectorHelper:
    def test_identity(self):
        assert rotate_vector((0, 0, 0, 1), (1, 2, 3)) == pytest.approx((1, 2, 3))

    def test_90_about_y_maps_x_to_minus_z(self):
        # +90° about +Y: quaternion (0, sin45, 0, cos45)
        s = math.sqrt(0.5)
        out = rotate_vector((0, s, 0, s), (1, 0, 0))
        assert out == pytest.approx((0, 0, -1), abs=1e-6)
