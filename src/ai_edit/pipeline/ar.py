"""AR asset pipeline — image-to-3D for placement via ``<model-viewer>``.

Phase 2 of the project. Takes one or more reference photos of an
object and returns the GLB + USDZ bytes needed to place that object
in AR through a browser:

::

    [ref1.jpg, ref2.jpg, ref3.jpg, ...]
        │
        ▼  Meshy · Multi-Image-to-3D
        │       returns glb + usdz
        │
        ▼
    ARAsset(glb_bytes, usdz_bytes)

The HTTP server stashes the bytes in memory and serves them under
``/ar/{id}/model.glb`` and ``/ar/{id}/model.usdz`` so a static
``<model-viewer>`` page can load them without any disk persistence.
That keeps the POC stateless from the caller's POV.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from ..providers import Meshy


@dataclass
class ARAsset:
    """Bundle of cross-platform AR-ready assets."""

    glb_bytes: bytes
    usdz_bytes: bytes


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/jpeg"


async def build_ar_asset(
    reference_paths: list[str | Path],
    *,
    target_polycount: int = 30000,
    meshy: Meshy | None = None,
) -> ARAsset:
    """Generate a GLB + USDZ from one or more reference photos.

    Parameters
    ----------
    reference_paths:
        Paths to reference photos of the object. Meshy works best with
        3–8 well-lit views from different angles.
    target_polycount:
        Max triangles in the output mesh; defaults to 30k which is a
        good balance for mobile/web delivery.
    meshy:
        Optional pre-built provider for dependency injection.

    Returns
    -------
    ARAsset
        ``glb_bytes`` for Android Scene Viewer / ``<model-viewer>``;
        ``usdz_bytes`` for iOS AR Quick Look. Either may be empty if
        Meshy fails to produce that format — callers should branch.

    Notes
    -----
    Meshy generations take **minutes**. This call holds the connection
    open until the asset is ready (or polling times out at 15 min). If
    interactive UX matters, wrap this in a job queue and let the
    client poll for status.
    """
    if not reference_paths:
        raise ValueError("build_ar_asset requires at least one reference path.")

    images: list[tuple[bytes, str]] = []
    for ref in reference_paths:
        p = Path(ref)
        images.append((p.read_bytes(), _guess_mime(p)))

    m = meshy or Meshy()
    result = await m.image_3d.generate(
        images,
        target_formats=["glb", "usdz"],
        target_polycount=target_polycount,
    )
    return ARAsset(glb_bytes=result.glb_bytes, usdz_bytes=result.usdz_bytes)
