"""High-level orchestration that composes providers into pipelines.

Currently exposes the POC's object-insertion pipeline. Add new
multi-provider workflows here (e.g. an AR asset pipeline that wires
Meshy → CDN → ``<model-viewer>`` URL generation) so that the
``providers/`` layer stays free of cross-vendor coupling.
"""

from .insert import InsertResult, insert_object

__all__ = ["InsertResult", "insert_object"]
