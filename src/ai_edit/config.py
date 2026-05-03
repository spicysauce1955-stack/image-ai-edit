from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv


def load_env(path: str | Path | None = None) -> None:
    p = Path(path) if path else Path.cwd() / ".env"
    load_dotenv(p)


def get_env(key: str, *, required: bool = True) -> str | None:
    value = os.getenv(key)
    if required and not value:
        raise EnvironmentError(
            f"Missing required env var: {key}. "
            f"Set it in .env or export {key}=..."
        )
    return value