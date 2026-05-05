"""Tiny env-loading helpers shared by every provider.

We keep this deliberately small: providers call :func:`get_env` in
their constructors so a missing key fails *fast and with a clear
message*, rather than at the moment of the first HTTP call.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_env(path: str | Path | None = None) -> None:
    """Load a ``.env`` file into ``os.environ``.

    Defaults to the ``.env`` next to the current working directory,
    which matches how the CLI is invoked from the repo root.

    ``override=True`` because the project's ``.env`` is the source of
    truth — without override, a stale shell export (e.g. an
    ``OPENAI_API_KEY`` left over from another tool) silently wins
    and you get auth errors that are very hard to debug.
    """
    p = Path(path) if path else Path.cwd() / ".env"
    load_dotenv(p, override=True)


def get_env(key: str, *, required: bool = True) -> str | None:
    """Read an env var, raising if ``required`` and the var is unset.

    The error message names the missing key explicitly so a fresh clone
    that forgot to copy ``.env.example`` gets actionable feedback.
    """
    value = os.getenv(key)
    if required and not value:
        raise EnvironmentError(
            f"Missing required env var: {key}. "
            f"Set it in .env or export {key}=..."
        )
    return value
