"""``ai_edit`` — modular Python wrappers for hosted AI image/text models.

Top-level convenience imports:

    >>> from ai_edit import Gemini, Replicate, FalAI, load_env
    >>> load_env()              # reads .env
    >>> gem = Gemini()          # picks up GEMINI_API_KEY

The actual POC pipeline lives in :mod:`ai_edit.pipeline.insert`; the
provider classes here are usable standalone if you want to call a
single endpoint without going through the full pipeline.
"""

from .config import load_env
from .providers import FalAI, Gemini, MiniMax, Replicate, ZhipuAI

__all__ = ["FalAI", "Gemini", "MiniMax", "Replicate", "ZhipuAI", "load_env"]
