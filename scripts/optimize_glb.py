"""Delivery-weight optimizer for generated GLBs.

Generated 3D (Hunyuan3D etc.) comes out heavy: ~500K triangles and
4K textures → tens of MB. Too big for web/AR delivery. This shrinks a
GLB to a deliverable size while staying **extension-free** (plain
glTF 2.0): no Draco, no meshopt, no KTX2/WebP — so it loads in
model-viewer, Android Scene Viewer, AND our `/ar/<id>/live` three.js
page (which uses a plain GLTFLoader with no extra decoders wired).

Three passes:
1. Upright   — rotate so the model stands (generated assets often lie
   flat) and sit it on the ground plane (min Y = 0).
2. Decimate  — quadric simplification to a target triangle count.
3. Textures  — downscale every PBR map to a max size; optional JPEG
   re-encode for the colour/ORM maps (normals kept lossless).

Uses trimesh (round-trips PBR baseColor/metallicRoughness/normal) +
fast-simplification for decimation. No Node, no external binaries.

Usage::

    .venv/bin/python scripts/optimize_glb.py in.glb out.glb
    .venv/bin/python scripts/optimize_glb.py in.glb out.glb --faces 40000 --texture-size 2048
    .venv/bin/python scripts/optimize_glb.py in.glb out.glb --no-upright
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import trimesh


def _stand_upright(mesh: trimesh.Trimesh) -> None:
    """Rotate so the thinnest axis is depth (Z) and the model stands.

    Generated meshes frequently come out with the thin axis along Y
    (lying flat). We detect the smallest-extent axis and, if it's Y,
    rotate -90° about X so the tall face becomes vertical. Then drop
    the model onto the ground plane (min Y = 0) and centre X/Z.
    """
    extents = mesh.extents  # (x, y, z)
    thin_axis = int(np.argmin(extents))
    if thin_axis == 1:  # thin along Y → lying flat; tip it upright
        mesh.apply_transform(
            trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0])
        )
    # Sit on the ground, centred horizontally.
    lo, hi = mesh.bounds
    cx = (lo[0] + hi[0]) / 2
    cz = (lo[2] + hi[2]) / 2
    mesh.apply_translation([-cx, -lo[1], -cz])


def _count_faces(glb_path: Path) -> int:
    import pygltflib

    g = pygltflib.GLTF2().load_binary(str(glb_path))
    return sum(
        g.accessors[p.indices].count // 3
        for m in g.meshes
        for p in m.primitives
        if p.indices is not None
    )


def _simplify_via_gltf_transform(in_path: Path, out_path: Path, ratio: float) -> None:
    """Decimate with gltf-transform (Node CLI) — preserves UVs + materials.

    trimesh's own quadric decimation drops the TextureVisuals (UVs are
    not remapped), so the result loses all textures. The meshoptimizer
    simplifier behind ``gltf-transform simplify`` remaps every vertex
    attribute, keeping the PBR material intact. Output stays plain
    glTF (no compression extensions).
    """
    if shutil.which("npx") is None:
        raise SystemExit(
            "npx (Node) is required for mesh decimation. Install Node, or "
            "pass --faces larger than the model's triangle count to skip it."
        )
    subprocess.run(
        [
            "npx", "--yes", "@gltf-transform/cli@latest", "simplify",
            str(in_path), str(out_path),
            "--ratio", f"{ratio:.4f}", "--error", "0.001",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _shrink_textures(
    mesh: trimesh.Trimesh, max_size: int, jpeg_color: bool
) -> None:
    """Downscale PBR maps to max_size; JPEG-encode colour + ORM maps.

    Normal maps stay lossless (PNG) — JPEG ringing corrupts normals.
    """
    mat = getattr(mesh.visual, "material", None)
    if mat is None:
        return
    from io import BytesIO

    from PIL import Image

    def _process(img: Image.Image | None, *, jpeg: bool) -> Image.Image | None:
        if img is None:
            return None
        w, h = img.size
        if max(w, h) > max_size:
            scale = max_size / max(w, h)
            img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
        if jpeg:
            # round-trip through JPEG so the encoded bytes (and the
            # format trimesh emits) are the compact ones.
            buf = BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85)
            buf.seek(0)
            img = Image.open(buf)
            img.load()
        return img

    for attr, is_color in (
        ("baseColorTexture", jpeg_color),
        ("metallicRoughnessTexture", jpeg_color),
        ("emissiveTexture", jpeg_color),
        ("normalTexture", False),
        ("occlusionTexture", jpeg_color),
    ):
        cur = getattr(mat, attr, None)
        if cur is not None:
            setattr(mat, attr, _process(cur, jpeg=is_color))


def optimize(
    in_path: Path,
    out_path: Path,
    *,
    target_faces: int,
    texture_size: int,
    upright: bool,
    jpeg_color: bool,
) -> dict:
    """Run the passes and write ``out_path``. Returns a small report."""
    before_faces = _count_faces(in_path)

    with tempfile.TemporaryDirectory(prefix="glb-opt-") as tmp:
        # 1. Decimate (UV/material-preserving) via gltf-transform.
        if before_faces > target_faces:
            simplified = Path(tmp) / "simplified.glb"
            _simplify_via_gltf_transform(
                in_path, simplified, ratio=max(0.01, target_faces / before_faces)
            )
            src = simplified
        else:
            src = in_path

        # 2. Upright + texture shrink in trimesh (no decimation here, so
        #    UVs + PBR material round-trip cleanly).
        scene = trimesh.load(src, force="scene")
        mesh = scene.to_geometry() if hasattr(scene, "to_geometry") else scene.dump(concatenate=True)
        if upright:
            _stand_upright(mesh)
        _shrink_textures(mesh, texture_size, jpeg_color)
        glb = mesh.export(file_type="glb")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(glb)

    return {
        "in_bytes": in_path.stat().st_size,
        "out_bytes": len(glb),
        "faces_before": before_faces,
        "faces_after": len(mesh.faces),
        "extents": [round(float(x), 3) for x in mesh.extents],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--faces", type=int, default=40000, help="Target triangle count (default 40000).")
    ap.add_argument("--texture-size", type=int, default=2048, help="Max texture dimension (default 2048).")
    ap.add_argument("--no-upright", action="store_true", help="Skip the stand-upright rotation.")
    ap.add_argument("--no-jpeg", action="store_true", help="Keep colour maps as PNG instead of JPEG.")
    args = ap.parse_args(argv)

    rep = optimize(
        Path(args.input),
        Path(args.output),
        target_faces=args.faces,
        texture_size=args.texture_size,
        upright=not args.no_upright,
        jpeg_color=not args.no_jpeg,
    )
    mb = lambda n: f"{n / 1e6:.1f} MB"
    print(f"in : {mb(rep['in_bytes'])}  ({rep['faces_before']:,} tris)")
    print(f"out: {mb(rep['out_bytes'])}  ({rep['faces_after']:,} tris)  "
          f"→ {rep['out_bytes'] / rep['in_bytes'] * 100:.0f}% of original")
    print(f"extents (x,y,z): {rep['extents']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
