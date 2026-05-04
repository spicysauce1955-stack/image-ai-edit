"""High-level orchestration that composes providers into pipelines.

Pipelines:

- :func:`insert_object` (in :mod:`.insert`) — 2D photo composite.

Add new multi-provider workflows as new modules in this package so
that the ``providers/`` layer stays free of cross-vendor coupling.
"""

from .insert import InsertResult, insert_object

__all__ = ["InsertResult", "insert_object"]
