"""High-level orchestration that composes providers into pipelines.

Pipelines:

- :func:`insert_object` (in :mod:`.insert`) — 2D photo composite.
- :func:`build_ar_asset` (in :mod:`.ar`) — image-to-3D for AR placement.

Add new multi-provider workflows as new modules in this package so
that the ``providers/`` layer stays free of cross-vendor coupling.
"""

from .ar import ARAsset, build_ar_asset
from .insert import InsertResult, insert_object

__all__ = ["ARAsset", "InsertResult", "build_ar_asset", "insert_object"]
