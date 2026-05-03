"""Concrete provider implementations.

Each module in this package wraps a single hosted vendor and exposes
one or more capability handlers that conform to the abstract classes in
:mod:`ai_edit.models.base`. See ``docs/architecture.md`` for the full
adapter pattern and ``docs/contributing.md`` for the recipe to add a
new provider.
"""

from .falai import FalAI
from .gemini import Gemini
from .meshy import Meshy
from .minimax import MiniMax
from .replicate import Replicate
from .zhipuai import ZhipuAI

__all__ = ["FalAI", "Gemini", "Meshy", "MiniMax", "Replicate", "ZhipuAI"]
