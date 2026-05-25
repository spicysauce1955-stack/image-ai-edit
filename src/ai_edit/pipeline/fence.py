"""Multi-section fence layout engine (Phase 8.A).

Pure geometry — no rendering, no network, no I/O. Given a `FenceSpec`
(panel + post components and a ground path), `compute_fence_layout`
returns the transforms for every post and panel needed to assemble a
fence, honouring the shared-post rule: a straight open run of N panels
has **N+1 posts** (a closed loop has N).

Invariants (see docs/multi-section-fence-design.md):
- Posts are always **plumb** (identity rotation — square posts).
- Panels are always **level** (yaw-only rotation; no pitch/roll/shear).
- Sloped ground is handled by **stepping**: posts plant at the ground
  height, panels mount level at a per-bay ``step_height``. No racking.

v1 scope: a single straight run (a 2-point path), ``fit="stretch"``.
Polylines/corners/closed loops are Phase 8.D and raise NotImplementedError.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

PostKind = Literal["line", "terminal", "corner", "gate"]
FitMode = Literal["stretch", "tile", "fixed_partial"]
StepRule = Literal["max", "min", "mean"]

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]  # (x, y, z, w)

_IDENT_QUAT: Quat = (0.0, 0.0, 0.0, 1.0)
_EPS = 1e-9


# --- small vector / quaternion helpers (stdlib only) -----------------------


def rotate_vector(q: Quat, v: Vec3) -> Vec3:
    """Rotate ``v`` by quaternion ``q`` (x, y, z, w). Useful for tests +
    the later bake step."""
    x, y, z, w = q
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _yaw_quat_from_dir(dx: float, dz: float) -> Quat:
    """Quaternion (rotation about +Y) mapping local +X onto the horizontal
    direction ``(dx, 0, dz)`` (``dx, dz`` need not be normalized).

    Rotating +X about +Y by θ gives ``(cosθ, 0, -sinθ)``, so we solve
    ``cosθ = dx, -sinθ = dz`` → ``θ = atan2(-dz, dx)``.
    """
    theta = math.atan2(-dz, dx)
    return (0.0, math.sin(theta / 2.0), 0.0, math.cos(theta / 2.0))


def _best_panel_count(length: float, nominal: float) -> int:
    """Whole-panel count minimizing |bay − nominal| (≥ 1).

    Equivalent to nearest-integer rounding but resolves the .5 boundary
    deterministically by comparing the actual bay error of floor vs ceil.
    """
    raw = length / nominal
    candidates = {max(1, math.floor(raw)), max(1, math.ceil(raw))}
    return min(candidates, key=lambda n: abs(length / n - nominal))


def _step_height(ha: float, hb: float, rule: StepRule) -> float:
    if rule == "min":
        return min(ha, hb)
    if rule == "mean":
        return (ha + hb) / 2.0
    return max(ha, hb)  # "max" (default): flush uphill, step over the gap


# --- data model ------------------------------------------------------------


@dataclass(frozen=True)
class ComponentRef:
    """A reusable GLB component in the ARStore + its assembly metadata.

    ``nominal_width`` is the component's extent along its local +X (the
    width axis a panel scales/tiles along), in metres.
    """

    asset_id: str
    nominal_width: float


@dataclass(frozen=True)
class FenceSpec:
    panel: ComponentRef
    post: ComponentRef
    path: tuple[Vec3, ...]  # ordered ground points (metres); y = ground height
    closed: bool = False
    fit: FitMode = "stretch"
    max_stretch: float = 0.12  # advisory tolerance; flagged on the layout
    step_rule: StepRule = "max"


@dataclass(frozen=True)
class Transform:
    position: Vec3
    rotation: Quat
    scale: Vec3


@dataclass(frozen=True)
class PostPlacement:
    transform: Transform
    kind: PostKind


@dataclass(frozen=True)
class PanelPlacement:
    transform: Transform  # always level (yaw-only)
    bay_length: float
    stretch: float
    step_height: float


@dataclass(frozen=True)
class FenceLayout:
    posts: tuple[PostPlacement, ...]
    panels: tuple[PanelPlacement, ...]
    within_tolerance: bool  # every bay's |stretch − 1| ≤ spec.max_stretch


# --- the engine ------------------------------------------------------------


def compute_fence_layout(spec: FenceSpec) -> FenceLayout:
    """Compute post + panel transforms for ``spec``.

    v1: single straight run (2-point path), ``fit="stretch"``. Raises
    ``NotImplementedError`` for polylines / closed loops / other fit
    modes (Phase 8.D / future).
    """
    path = spec.path
    if len(path) < 2:
        raise ValueError("FenceSpec.path needs at least 2 points")
    if spec.closed or len(path) > 2:
        raise NotImplementedError(
            "polyline / corner / closed-loop layouts are Phase 8.D; "
            "v1 handles a single straight run (a 2-point open path)"
        )
    if spec.fit != "stretch":
        raise NotImplementedError(
            f"fit={spec.fit!r} is reserved; v1 implements 'stretch' only"
        )

    nominal = spec.panel.nominal_width
    if nominal <= 0:
        raise ValueError("panel.nominal_width must be > 0")

    a, b = path[0], path[1]
    dx, dz = b[0] - a[0], b[2] - a[2]
    length = math.hypot(dx, dz)  # horizontal span (stepping ignores y here)
    if length <= _EPS:
        raise ValueError("zero-length fence segment (a and b coincide in XZ)")

    n = _best_panel_count(length, nominal)
    bay = length / n
    stretch = bay / nominal
    within_tolerance = abs(stretch - 1.0) <= spec.max_stretch

    yaw = _yaw_quat_from_dir(dx, dz)

    # Posts: n+1, plumb, planted at the linearly-interpolated ground height.
    posts: list[PostPlacement] = []
    for i in range(n + 1):
        t = i / n
        pos: Vec3 = (
            a[0] + dx * t,
            a[1] + (b[1] - a[1]) * t,  # ground height
            a[2] + dz * t,
        )
        kind: PostKind = "terminal" if i in (0, n) else "line"
        posts.append(PostPlacement(Transform(pos, _IDENT_QUAT, (1.0, 1.0, 1.0)), kind))

    # Panels: n, level, between consecutive posts, mounted at step_height.
    panels: list[PanelPlacement] = []
    for i in range(n):
        pa = posts[i].transform.position
        pb = posts[i + 1].transform.position
        step_h = _step_height(pa[1], pb[1], spec.step_rule)
        center: Vec3 = ((pa[0] + pb[0]) / 2.0, step_h, (pa[2] + pb[2]) / 2.0)
        panels.append(
            PanelPlacement(
                transform=Transform(center, yaw, (stretch, 1.0, 1.0)),
                bay_length=bay,
                stretch=stretch,
                step_height=step_h,
            )
        )

    return FenceLayout(tuple(posts), tuple(panels), within_tolerance)
