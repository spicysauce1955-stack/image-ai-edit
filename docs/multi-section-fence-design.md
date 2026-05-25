---
created: 2026-05-25
tags: [design, ar, fence]
---

# Multi-section fence — solution design

Canonical design for Phase 8 of `docs/ar-plan.md`: assembling a fence of
multiple *combined* sections in AR, where adjacent sections share posts.
Grounded in `research/multi-section-fence/findings.md` (kit-of-parts +
runtime assembly) and real fence-construction standards.

> **Hard constraint — keep existing features intact.** Phase 8 is purely
> additive. The 2D pipeline (`pipeline/insert.py`, `/api/insert`, pole/
> polygon/overlay handling), the AR routes (`/ar/{id}`, `/ar/{id}/live`,
> `/catalog`, `/api/catalog`), `FalAIMultiImageTo3D`, `ARStore`,
> `asset_validate`, `optimize_glb`, and the catalog are **reused, not
> modified**. New modules / routes / scripts only. The existing 189 tests
> stay green.

---

## 1. Problem & scope

Build an arbitrary-length fence from reusable components. The defining
fact: a fence is **panels separated by shared posts**.

- Straight open run: **posts = panels + 1**
- Closed loop (enclosure): **posts = panels**

Instancing a whole "section" (panel + 2 posts) N times double-counts the
shared boundary posts. The fix, used by every modular tool (Unreal/Unity/
Blender/Houdini), is a **kit of parts**: place POSTS at boundaries,
PANELS between them.

**v1 scope:** straight runs and simple polylines on flat ground.
Corners/enclosures and slope are later sub-phases (see §11).

---

## 2. Domain model (grounded in real fencing)

From the construction-standards research:

- **Panels** come in fixed nominal widths (commonly 6 ft / 8 ft). Real
  installs keep bay-width mismatch small (< ~10%); they don't arbitrarily
  stretch panels.
- **Posts have types** with different geometry/role: **line** (field),
  **terminal/end**, **corner**, **gate**, **brace**. v1 uses one post
  component for all positions; the model carries `kind` so later phases
  can swap in distinct terminal/corner posts.
- **Rails/pickets**: ~1 rail per 24" of height (6 ft privacy = 3 rails);
  pickets per panel = `ceil(panelWidth / (picketWidth + gap))`. Relevant
  only if we ever generate parametric panels; with a baked panel GLB this
  is descriptive metadata.
- **Slope**: *stepped* (panels stay rectangular, step down the grade) vs
  *racked* (panels shear into parallelograms following grade; pickets stay
  plumb, rails follow the slope). Vinyl racks ~10° naturally.
- **Gates** are special sections with terminal posts.
- **Units**: physical fencing is imperial inches; glTF/WebXR is **meters,
  +Y up, +Z forward**. We store the spec in **meters** and treat imperial
  as a display concern.

---

## 3. Data structures (new — `pipeline/fence.py`)

All frozen dataclasses; pure data, no rendering.

```python
PostKind = Literal["line", "terminal", "corner", "gate"]
SlopeMode = Literal["stepped", "racked"]   # v1 implements "stepped"
FitMode   = Literal["stretch", "tile", "fixed_partial"]  # v1: "stretch"

@dataclass(frozen=True)
class ComponentRef:
    """A reusable GLB component in the ARStore + its assembly metadata."""
    asset_id: str          # ARStore scene id (serves at /ar/<id>/model.glb)
    nominal_width: float   # metres along the local +X (width) axis
    # origin convention (see §4): base, mid-width, mid-depth.

@dataclass(frozen=True)
class FenceSpec:
    panel: ComponentRef
    post: ComponentRef
    path: tuple[Vec3, ...]      # ordered points (metres), the fence line
    closed: bool = False        # True → enclosure (posts = panels)
    fit: FitMode = "stretch"
    slope_mode: SlopeMode = "stepped"
    max_stretch: float = 0.12   # |bay/nominal − 1| tolerance before re-count

@dataclass(frozen=True)
class Transform:
    position: Vec3
    rotation: tuple[float, float, float, float]  # quaternion (x,y,z,w)
    scale: Vec3

@dataclass(frozen=True)
class PostPlacement:
    transform: Transform
    kind: PostKind

@dataclass(frozen=True)
class PanelPlacement:
    transform: Transform
    bay_length: float           # metres
    stretch: float              # scale applied on width axis (1.0 = nominal)

@dataclass(frozen=True)
class FenceLayout:
    posts: tuple[PostPlacement, ...]
    panels: tuple[PanelPlacement, ...]
    # invariants (asserted in tests):
    #   open  : len(posts) == len(panels) + 1
    #   closed: len(posts) == len(panels)
```

`compute_fence_layout(spec) -> FenceLayout` is the **pure heart** of the
feature — no AR, no network, fully unit-testable. First deliverable.

---

## 4. Component conventions

A panel/post GLB must declare a known local frame so assembly can place
it deterministically:

- **Axes**: +Y up, +Z depth (thickness), **+X = width** (the axis a panel
  scales/tiles along). This matches what `optimize_glb`'s upright pass
  produces (X = width, Y = height, Z = thin depth).
- **Origin**: panel origin at **base, mid-width, mid-depth** → bottom-
  centre. A post's origin at **base, centre** → bottom-centre. So placing
  = set position to the world point, sit on ground at y=0.
- **Nominal width** carried in `ComponentRef.nominal_width` (metres),
  read from the GLB's X-extent at component-build time, and mirrored into
  the GLB `node.extras` (`{"role":"panel","nominalWidth":W}`) so a baked
  asset is self-describing. (glTF exporters preserve `node.extras`.)
- **Seam anchors**: panel left/right faces at `x = ±nominalWidth/2`;
  posts sit at panel boundaries, so a panel spanning posts at `a,b` has
  its seams coincide with the post centres.

Components are produced by the Phase 8.B prep (panel-only + post-only
crops → image→3D → `optimize_glb`), and `optimize_glb` already emits the
upright, base-origin orientation — so the convention is mostly already
true; 8.B just records `nominal_width` + writes `node.extras`.

---

## 5. Layout algorithm

### 5.1 Single straight segment a→b

```
seg     = b - a
L       = |seg_horizontal|                 # horizontal length (stepped)
n       = max(1, round(L / panel.nominal_width))   # whole panels
bay     = L / n                            # uniform bay length
stretch = bay / panel.nominal_width        # ~within max_stretch by construction
```

`round()` keeps `stretch` within ≈±10% for reasonable n (worst case at
the `.5` boundary), matching the physical < ~10% mismatch rule — so the
default `fit="stretch"` is visually acceptable *and* the math self-limits.
If `|stretch-1| > max_stretch` for small n, nudge n by ±1 and pick the
smaller error.

- **Posts** at distances `i*bay` for `i in 0..n` (n+1 posts).
- **Panels** between consecutive posts: for panel `i`,
  - `pa, pb` = post positions `i, i+1`
  - `center = (pa + pb) / 2`
  - `rotation` = align local +X to `normalize(pb - pa)` (see §6)
  - `scale = (stretch, 1, 1)`

### 5.2 Fit modes (why not naive stretch everywhere)

Research caution: uniformly scaling a whole panel mesh distorts pickets +
UVs. Three strategies, in increasing fidelity/complexity:

- **`stretch`** (v1 default): scale the baked panel on +X by `stretch`.
  Acceptable because `round()` bounds it to ~±10%. Simplest; works with a
  single baked panel GLB.
- **`fixed_partial`**: place `floor(L/W)` nominal panels + one trimmed
  partial bay. No distortion on full panels; needs a clip/trim of the
  last panel.
- **`tile`**: repeat the *infill* (pickets) to fill the bay, keep posts/
  rails fixed. Best fidelity but requires the panel authored as separable
  picket+rail geometry (our generated GLB isn't) — future, when we make
  parametric panels.

v1 ships `stretch`; the `FitMode` enum reserves the others.

### 5.3 Polyline (multiple segments) — Phase 8.D

For path points `p0..pk`:
- Lay out each segment `p(i)→p(i+1)` with §5.1, but **don't duplicate the
  shared vertex post** — the end post of segment i is the start post of
  segment i+1. Dedup by indexing post positions (snap within ε).
- At each interior vertex place a **corner post** (`kind="corner"`)
  oriented to the **bisector** of the two segment directions (§6.3).
- **Closed loop** (`closed=True`): treat `p0` and `pk` as the same vertex →
  posts = panels.

### 5.4 Slope

- **`stepped`** (v1): compute layout on the horizontal projection; set
  each post's y to the sampled ground height; panels stay rectangular and
  level, sitting at the lower post's height (or spanning with a small
  step). Panels never distort.
- **`racked`** (8.E): panel becomes a parallelogram — pickets stay plumb,
  rails follow grade. This is a **shear**, not a rotation (a rotation
  would tilt the pickets). Either bake a racked panel variant or apply a
  shear matrix. Deferred.

---

## 6. Transform math (the research gap — supplied here)

three.js: `Matrix4`, `Quaternion`, `Vector3`. Right-handed, +Y up.

### 6.1 Place a panel between posts `a`, `b` (level)

```
d   = normalize( (b - a) projected onto XZ plane )   # horizontal dir
up  = (0, 1, 0)
xA  = d                       # panel width axis → segment direction
zA  = normalize(cross(xA, up))
yA  = cross(zA, xA)           # = up (re-orthonormalized)
R   = Matrix4 from basis columns (xA, yA, zA)
q   = Quaternion.setFromRotationMatrix(R)
pos = (a + b) / 2             # origin is base-mid, so y = ground height
scale = (stretch, 1, 1)
```

In three.js this is `instanceMatrix.compose(pos, q, scale)` written via
`InstancedMesh.setMatrixAt(i, m)`.

### 6.2 Post placement

Square posts are radially symmetric, so a line post needs no special
yaw. Place at `pos = postPoint` (y = ground), identity rotation, unit
scale. One `InstancedMesh` for all posts → shared posts are a single
instance (dedup by position).

### 6.3 Corner post + panel angle (Phase 8.D)

At interior vertex with incoming unit dir `u` (a→vertex) and outgoing
unit dir `v` (vertex→b):
- interior angle `θ = acos( clamp( dot(-u, v), -1, 1 ) )`
- **corner-post yaw**: orient to the bisector `bis = normalize(-u + v)`
  (square posts: cosmetic; profiled posts: required).
- adjacent panels keep their own segment rotations from §6.1 — they
  simply meet at the corner post.
- if we ever miter rails: miter angle `= 90° − θ/2` from each side.

### 6.4 Racked shear (Phase 8.E)

For grade angle `φ` along the segment, shear the panel so rails rotate by
`φ` while the local +Y (pickets) stays world-up: a shear in the X–Y plane,
`y' = y, x' = x + y·tan(φ_local)` in panel-local space (or use a
purpose-baked racked mesh). Deferred.

---

## 7. Assembly

### 7.1 Runtime (primary) — new WebXR page

A new page (`/ar/{id}/fence`, or a `mode=fence` flag on the live page —
**a new route either way; `/ar/{id}/live` is untouched**):

1. Load the PANEL + POST component GLBs once (GLTFLoader).
2. Define the ground path via **WebXR hit-test**: tap to drop posts (or
   tap start→end and auto-divide). Collect poses → polyline → **RDP
   simplify** → quantize to bays.
3. Fetch the layout from `POST /api/fence/layout` (the §3 pure function —
   **single source of truth**, no JS re-implementation) OR compute
   client-side from the same spec; v1 calls the API to avoid drift.
4. Build two `THREE.InstancedMesh` batches (posts, panels) and write
   per-instance matrices via `setMatrixAt`. Dedup posts by position.
5. Re-layout live as the user extends the path (`DynamicDrawUsage`).

Stays **extension-free** (plain `InstancedMesh` objects, no glTF
extension) → compatible with the existing bare GLTFLoader on `/live`.

### 7.2 Bake-to-GLB (secondary) — `scripts/bake_fence.py` / API

For model-viewer / iOS Quick Look / sharing (can't assemble at runtime):
take a `FenceSpec` → layout → instantiate each component at its transform
→ merge into one **extension-free** GLB via the existing
`optimize_glb`/gltf-transform tooling. Served via the normal `/ar/{id}`
route — no new viewer code.

---

## 8. API design (new routes, additive)

- `POST /api/fence/layout` — body = `FenceSpec` JSON; returns
  `FenceLayout` JSON (posts + panels transforms + counts). Thin wrapper
  over `compute_fence_layout`. No asset bytes.
- `POST /api/fence/bake` — body = `FenceSpec`; runs the bake, stores the
  GLB under a new scene id, returns `{scene_id, ar_url}`. Background-job
  shaped like `/api/generate3d` (Phase 7.C) since bake + optimize takes
  seconds.

Both live in a new `server/fence_routes.py` mounted alongside the others;
`create_app` includes the router. Existing routes unchanged.

---

## 9. WebXR UX flow (v1, straight run)

1. Pick a fence style (panel+post component pair) from the catalog.
2. Enter AR; reticle on the ground.
3. Tap **start**, tap **end** → a straight run is laid out and previewed
   (posts + panels), with the panel count shown.
4. Drag the end / adjust bay count; live re-layout.
5. "Place" locks it; "Snapshot" (reuses Phase 6.C idea) optional.

Mirrors the existing 2D pole UX (place poles → sections between) so the
mental model carries over.

---

## 10. Integration & additive guarantees

| New (Phase 8) | Reuses (unchanged) |
|---|---|
| `pipeline/fence.py` (FenceSpec, layout) | `ARStore`, `asset_validate` |
| `server/fence_routes.py` (`/api/fence/*`) | `create_app` include pattern |
| `scripts/build_fence_components.py` (8.B) | `FalAIMultiImageTo3D`, nano-banana isolate, `optimize_glb` |
| `scripts/bake_fence.py` (8.E) | `optimize_glb` / gltf-transform |
| new WebXR fence page (8.C) | `ar_routes` building blocks; **not** `/live` |
| tests under `tests/pipeline`, `tests/server` | existing suite stays green |

No edits to `insert.py`, the `/api/insert` route, the pole/overlay code,
`/ar/{id}`, `/ar/{id}/live`, `/catalog`, `FalAIMultiImageTo3D`,
`optimize_glb`, or the catalog. The 2D-pole → FenceSpec convergence is a
*future* additive adapter, not a change to 2D code.

---

## 11. Phasing (each a small, tested, committed PR)

- **8.A — Layout engine.** `pipeline/fence.py`: dataclasses +
  `compute_fence_layout` (straight run, stretch fit, stepped). Pure;
  heavy unit tests (§12). **No AR, no network. Start here.**
- **8.B — Components.** `build_fence_components.py`: image → panel-only +
  post-only crops → image→3D → `optimize_glb` → store + `node.extras`
  width. Mocked tests; one gated live test.
- **8.C — Straight-run AR.** New WebXR fence page + `/api/fence/layout`.
  Tap start→end, InstancedMesh assembly, shared posts. Static-wiring +
  route tests.
- **8.D — Polyline + corners + enclosures.** Layout-engine corner posts &
  closed loops; UI multi-tap path.
- **8.E — Bake-to-GLB + racked slope.** `bake_fence.py`, `/api/fence/bake`;
  racked shear in the layout engine.

### Acceptance criteria (per phase)
- 8.A: `posts == panels + 1` (open) / `== panels` (closed); stretch ≤
  `max_stretch` for n ≥ 2; deterministic transforms; degenerate paths
  rejected.
- 8.C: a real 2-post tap produces a visually continuous run with N+1
  posts on a phone; no duplicated shared posts.
- 8.E: baked GLB opens in model-viewer + Quick Look, extension-free.

---

## 12. Testing strategy

- **8.A (pure, the bulk):** post-count invariants (open/closed, n=1..50);
  shared-post dedup on polylines; stretch within tolerance; corner posts
  appear at vertices; closed-loop post==panel; degenerate inputs
  (single point, zero-length segment, duplicate points) raise cleanly;
  transform sanity (panel midpoint between posts, width axis aligned).
- **8.B:** mocked provider/isolate; assert two components produced with
  recorded `nominal_width` + `node.extras`. One `RUN_NETWORK_TESTS=1`
  live test.
- **8.C:** `/api/fence/layout` returns correct JSON shape + counts; fence
  page HTML wires InstancedMesh + fetches the layout endpoint.
- Existing 189 tests must stay green throughout.

---

## 13. Open decisions

1. **Fit mode v1** — `stretch` (simplest, ≤10% distortion). Upgrade to
   `tile`/`fixed_partial` only once panels are parametric. (Recommend
   ship `stretch`.)
2. **Layout source of truth** — Python `/api/fence/layout` consumed by
   JS (no drift) vs porting to JS. (Recommend Python endpoint.)
3. **Post variants** — single post component for all positions in v1;
   distinct terminal/corner/gate posts deferred. (Recommend single.)
4. **Path entry** — start→end (auto-divide) first; freehand multi-tap
   polyline in 8.D.
5. **Units** — store metres; imperial display later.
