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
- **Slope — STEPPED ONLY (design decision).** Posts are **always
  vertical/plumb** and panels are **always level rectangles** — neither
  is ever inclined. On sloped ground the fence **steps down**: each bay
  is offset vertically from its neighbour, like stairs. *Racked/raked*
  fences (tilted panels following the grade) are explicitly **out of
  scope** — there is no panel pitch/roll and no post tilt, ever.
- **Gates** are special sections with terminal posts.
- **Units**: physical fencing is imperial inches; glTF/WebXR is **meters,
  +Y up, +Z forward**. We store the spec in **meters** and treat imperial
  as a display concern.

---

## 3. Data structures (new — `pipeline/fence.py`)

All frozen dataclasses; pure data, no rendering.

```python
PostKind = Literal["line", "terminal", "corner", "gate"]
FitMode  = Literal["stretch", "tile", "fixed_partial"]  # v1: "stretch"
# No SlopeMode: posts are always plumb and panels always level. Sloped
# ground is handled by stepping (per-post ground height), never tilting.

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
    path: tuple[Vec3, ...]      # ordered points (metres); y = ground height
    closed: bool = False        # True → enclosure (posts = panels)
    fit: FitMode = "stretch"
    max_stretch: float = 0.12   # |bay/nominal − 1| tolerance before re-count
    # Slope is always handled by stepping; no slope mode / no tilt.

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
    transform: Transform        # always level (yaw only; no pitch/roll)
    bay_length: float           # metres (horizontal span)
    stretch: float              # scale applied on width axis (1.0 = nominal)
    step_height: float          # bay's level mount height (metres) — stair step

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

### 5.4 Slope — stepped only

Posts are always vertical and panels always level — the fence never
tilts; it **steps**. Algorithm:

- All horizontal layout (bay count, post X/Z, panel rotation) is computed
  on the **horizontal projection** of the path (ignore y). So bays and
  panel widths are unaffected by grade.
- Each **post** is planted **plumb** at its boundary, base y = the
  sampled ground height at that point. (Downhill posts simply stand
  taller above grade.)
- Each **panel** is a **level rectangle** mounted at a single
  `step_height` for that bay — the bay's mount height (e.g. the higher of
  its two posts' ground heights, so the panel is flush on the uphill side
  and steps over the gap on the downhill side; the exact rule is a
  parameter). Adjacent bays differ in `step_height` by the grade drop →
  the stair-step look.
- **No pitch, no roll, no shear, ever.** A panel's only rotation is yaw
  to follow the horizontal segment direction (§6.1).

On flat ground every `step_height` is equal and it reduces to a straight
level run.

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
`InstancedMesh.setMatrixAt(i, m)`. Note `d` is the **horizontal**
direction and `up` is world +Y, so the panel is **level by construction**
— yaw only, never pitched or rolled. `pos.y = step_height` (§5.4) for the
bay; on a slope the y differs between bays (the step), but each panel
stays level.

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

### 6.4 (removed) — no racking

Racked/raked panels are out of scope (see §2, §5.4). There is no shear
and no panel/post tilt anywhere in the system. Sloped ground is handled
entirely by `step_height` per bay (§5.4) with level panels and plumb
posts.

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
  `compute_fence_layout` (straight run, stretch fit, **stepping built in**
  — level panels + plumb posts from per-post ground heights). Pure;
  heavy unit tests (§12). **No AR, no network. Start here.**
- **8.B — Components.** `build_fence_components.py`: image → panel-only +
  post-only crops → image→3D → `optimize_glb` → store + `node.extras`
  width. Mocked tests; one gated live test.
- **8.C — Straight-run AR.** New WebXR fence page + `/api/fence/layout`.
  Tap start→end, InstancedMesh assembly, shared posts. Static-wiring +
  route tests.
- **8.D — Polyline + corners + enclosures.** Layout-engine corner posts &
  closed loops; UI multi-tap path.
- **8.E — Bake-to-GLB.** `bake_fence.py`, `/api/fence/bake` — assemble a
  FenceSpec into one extension-free GLB for model-viewer / Quick Look /
  sharing. (No racking work — stepping is already in 8.A.)

### Acceptance criteria (per phase)
- 8.A: `posts == panels + 1` (open) / `== panels` (closed); stretch ≤
  `max_stretch` for n ≥ 2; **every panel transform is level (yaw-only,
  zero pitch/roll) and every post is plumb**; stepping offsets bays by
  the grade drop; deterministic transforms; degenerate paths rejected.
- 8.C: a real 2-post tap produces a visually continuous run with N+1
  posts on a phone; no duplicated shared posts; on a sloped tap the run
  steps (panels level, posts plumb).
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

**Settled (not open):** slope is **stepped only** — posts always plumb,
panels always level; no racking/tilt/shear anywhere.

### Step mount-height rule (the one stepping detail to pin in 8.A)
For a bay between posts at ground heights `h_a`, `h_b`, the panel's level
`step_height` defaults to `max(h_a, h_b)` (flush on the uphill side,
steps over the downhill gap). Exposed as a parameter so a "centre" or
"min" rule can be chosen later; doesn't affect the level/plumb invariant.
