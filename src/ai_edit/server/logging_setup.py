"""Centralized logging configuration for the AR app.

Phase 4.D of the AR plan. Keeps stdlib ``logging`` config in one
place so the AR + catalog routes can emit consistent, observable
events without a new dependency.

Loggers used by the AR delivery path:

- ``ai_edit.ar`` — :mod:`ai_edit.server.ar_routes` HTML + asset routes
- ``ai_edit.catalog`` — :mod:`ai_edit.server.catalog_routes` API +
  browse routes

Production deployments that want structured JSON output should
attach their own formatter / handler to the ``ai_edit`` parent
logger after :func:`setup_logging` runs.
"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "ai_edit"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the ``ai_edit`` logger and return it.

    Idempotent — calling more than once is safe (the second call is a
    no-op). This matters because :func:`create_app` is invoked once
    per worker but tests sometimes build multiple apps in a session.

    Emits to stderr in the human-readable format below. Production
    callers wanting JSON should add their own handler to the
    ``ai_edit`` logger and/or set ``propagate=False`` to silence the
    default stream handler.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    # Keep the propagation default (True) so a parent root logger
    # configured by the host application can still see our events.
    return logger
