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
from typing import Callable
from urllib.parse import urljoin

import httpx

# A URL rewriter takes the relative URI as written in the .gltf plus
# the base URL of the .gltf (its parent directory, with trailing
# slash) and returns the absolute URL to fetch the resource from.
# Returning the urljoin of the two arguments is the identity / default
# rewriter — see :data:`default_rewriter`.
UrlRewriter = Callable[[str, str], str]


def default_rewriter(relative_uri: str, base_url: str) -> str:
    """Resolve ``relative_uri`` against ``base_url`` (the .gltf's parent).

    This is the well-behaved-source rewriter — used by any catalog
    entry that doesn't override. Khronos Box.gltf and friends work
    with this rewriter unchanged.
    """
    return urljoin(base_url, relative_uri)


def poly_haven_rewriter(relative_uri: str, base_url: str) -> str:
    """Rewrite a relative ref into its actual Poly Haven CDN URL.

    Poly Haven's .gltf assumes textures live at ``textures/<filename>``
    next to the .gltf, but the CDN serves them in a parallel
    ``<root>/<ext>/<res>/<slug>/<filename>`` tree. ``.bin`` files do
    live next to the .gltf and need no rewrite.

    Path shape::

        .gltf:    .../Models/gltf/<res>/<slug>/<slug>_<res>.gltf
        .bin:     .../Models/gltf/<res>/<slug>/<slug>.bin          (default urljoin works)
        texture:  .../Models/<ext>/<res>/<slug>/<filename>.<ext>   (rewrite needed)
    """
    if not relative_uri.startswith("textures/"):
        return default_rewriter(relative_uri, base_url)
    filename = relative_uri[len("textures/"):]
    # File extension drives the CDN sub-tree (`/jpg/`, `/png/`, `/exr/`).
    ext = filename.rsplit(".", 1)[-1].lower()
    new_base = base_url.replace("/Models/gltf/", f"/Models/{ext}/", 1)
    return new_base + filename


# Registry of named rewriters. The catalog manifest references these
# by name (``"poly_haven"``) so JSON entries stay declarative.
REWRITERS: dict[str, UrlRewriter] = {
    "default": default_rewriter,
    "poly_haven": poly_haven_rewriter,
}


def get_rewriter(name: str | None) -> UrlRewriter:
    """Look up a rewriter by name. ``None`` returns the default.

    Raises :class:`KeyError` for unknown names — keeps catalog typos
    loud.
    """
    if name is None:
        return default_rewriter
    if name not in REWRITERS:
        raise KeyError(
            f"unknown url rewriter {name!r}; known: {sorted(REWRITERS)}"
        )
    return REWRITERS[name]


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
    rewriter: UrlRewriter | None = None,
) -> Path:
    """Download the ``.gltf`` JSON and every external resource it
    references into ``dest_dir``, preserving relative paths.

    The optional ``rewriter`` adapts a relative URI to its actual
    fetch URL — useful for sources like Poly Haven that ship .gltf
    files whose paths don't resolve naively against the file's own
    URL. Defaults to :func:`default_rewriter` (plain urljoin).

    Returns the path of the downloaded ``.gltf`` file.
    """
    rewriter = rewriter or default_rewriter

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
        # Save at the relative path so pygltflib can find the file
        # where the .gltf expects it. Fetch from whatever the rewriter
        # says is the real URL.
        _download_to(client, rewriter(relative, base), dest_dir / relative)

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
    # Inline every external image as a base64 data URI and pull every
    # external buffer into the GLB's binary blob. After these two
    # calls the in-memory glTF has no external references left.
    #
    # We use ``DATAURI`` for images even though ``BUFFERVIEW`` would
    # be more space-efficient — pygltflib's BUFFERVIEW conversion is
    # documented as broken for image data (silently no-ops; see
    # https://gitlab.com/dodgyville/pygltflib/issues for the upstream
    # bug). DATAURI roughly 33%-inflates image bytes via base64 but
    # produces a fully self-contained GLB that model-viewer accepts.
    gltf.convert_images(pygltflib.ImageFormat.DATAURI)
    gltf.convert_buffers(pygltflib.BufferFormat.BINARYBLOB)

    glb_path = gltf_path.parent / "_bundled.glb"
    gltf.save_binary(str(glb_path))
    return glb_path.read_bytes()


def bundle_remote_gltf(
    gltf_url: str,
    *,
    client: httpx.Client,
    rewriter: UrlRewriter | None = None,
) -> bytes:
    """Download ``gltf_url`` + its external resources, return a
    self-contained GLB.

    Top-level convenience that combines :func:`download_gltf_assembly`
    and :func:`assemble_to_glb`. All disk work is confined to a temp
    directory that's cleaned up before this function returns.
    """
    with tempfile.TemporaryDirectory(prefix="ai-edit-bundle-") as tmp:
        gltf_path = download_gltf_assembly(
            gltf_url, Path(tmp), client=client, rewriter=rewriter
        )
        return assemble_to_glb(gltf_path)
