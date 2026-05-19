"""Bundle a remote glTF + external textures into a self-contained GLB.

Phase 4.A of the AR plan. The AR routes serve single-file binary GLBs
out of the :class:`ARStore`. Many free model libraries (notably Poly
Haven) ship glTF assets as a JSON file + separate texture / buffer
files, which our delivery model can't serve directly. This module
closes that gap.

Usage from the fetcher::

    glb_bytes = bundle_remote_gltf(
        "https://dl.polyhaven.org/.../planter_box_01_2k.gltf",
        client=httpx_client,
    )
    store.put(scene_id, Scene3DAsset(data=glb_bytes, mime_type=MIME_GLB, ...))

``pygltflib`` is an optional dependency (``pip install ai-edit[bundle]``);
it's imported lazily so the rest of the codebase still loads if the
extra isn't installed. A clear ImportError is raised at call time
rather than at module import.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import httpx


def _require_pygltflib():
    """Import :mod:`pygltflib` lazily so the runtime doesn't require it.

    Raises a helpful :class:`ImportError` if the optional extra isn't
    installed, rather than failing at module import time.
    """
    try:
        import pygltflib  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised by the extras-missing path
        raise ImportError(
            "pygltflib is required for texture bundling. Install with:\n"
            "    uv pip install -p .venv/bin/python -e .[bundle]"
        ) from exc
    return pygltflib


def discover_external_refs(gltf_json: dict) -> list[str]:
    """Return relative URIs referenced by buffers + images in ``gltf_json``.

    Skips data-URI refs (already embedded) and absolute URLs (the
    spec allows them; we don't bundle those for now since they're
    rare and a user feeding an absolute URL probably knows what they
    want).
    """
    refs: list[str] = []
    for section in ("buffers", "images"):
        for item in gltf_json.get(section, []) or []:
            uri = (item or {}).get("uri")
            if not uri:
                continue
            if uri.startswith("data:"):
                continue
            if uri.startswith(("http://", "https://")):
                continue
            refs.append(uri)
    return refs


def _download_to(client: httpx.Client, url: str, dest: Path) -> None:
    """GET ``url`` and write the body to ``dest``, mkdir-ing as needed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = client.get(url)
    response.raise_for_status()
    dest.write_bytes(response.content)


def download_gltf_assembly(
    gltf_url: str,
    dest_dir: Path,
    *,
    client: httpx.Client,
) -> Path:
    """Download the ``.gltf`` JSON and every external resource it
    references into ``dest_dir``, preserving relative paths.

    Returns the path of the downloaded ``.gltf`` file.
    """
    gltf_response = client.get(gltf_url)
    gltf_response.raise_for_status()
    gltf_json = gltf_response.json()

    # Persist the JSON verbatim — pygltflib will read it back later.
    # Filename mirrors the URL's last segment so it doesn't shadow
    # any external resource with the same stem.
    gltf_name = gltf_url.rsplit("/", 1)[-1] or "model.gltf"
    gltf_path = dest_dir / gltf_name
    gltf_path.parent.mkdir(parents=True, exist_ok=True)
    gltf_path.write_text(json.dumps(gltf_json))

    base = gltf_url.rsplit("/", 1)[0] + "/"
    for relative in discover_external_refs(gltf_json):
        _download_to(client, urljoin(base, relative), dest_dir / relative)

    return gltf_path


def assemble_to_glb(gltf_path: Path) -> bytes:
    """Use :mod:`pygltflib` to convert an on-disk .gltf assembly into a
    self-contained GLB and return its bytes.

    Assumes external resources referenced by the .gltf already live at
    their relative paths next to ``gltf_path`` — see
    :func:`download_gltf_assembly`.
    """
    pygltflib = _require_pygltflib()

    gltf = pygltflib.GLTF2().load(str(gltf_path))
    # Pull every external image into a bufferView and every external
    # buffer into the GLB's binary blob. After these two calls the
    # in-memory glTF has no external references left.
    gltf.convert_images(pygltflib.ImageFormat.BUFFERVIEW)
    gltf.convert_buffers(pygltflib.BufferFormat.BINARYBLOB)

    glb_path = gltf_path.parent / "_bundled.glb"
    gltf.save_binary(str(glb_path))
    return glb_path.read_bytes()


def bundle_remote_gltf(
    gltf_url: str,
    *,
    client: httpx.Client,
) -> bytes:
    """Download ``gltf_url`` + its external resources, return a
    self-contained GLB.

    Top-level convenience that combines :func:`download_gltf_assembly`
    and :func:`assemble_to_glb`. All disk work is confined to a temp
    directory that's cleaned up before this function returns.
    """
    with tempfile.TemporaryDirectory(prefix="ai-edit-bundle-") as tmp:
        gltf_path = download_gltf_assembly(gltf_url, Path(tmp), client=client)
        return assemble_to_glb(gltf_path)
