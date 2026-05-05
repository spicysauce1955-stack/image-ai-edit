"""``ai_edit`` — modular Python wrappers for hosted AI image/text models.

Top-level convenience imports:

    >>> from ai_edit import Gemini, OpenAI, FalAI, load_env
    >>> load_env()              # reads .env
    >>> oai = OpenAI()          # picks up OPENAI_API_KEY
"""

from .config import load_env
from .providers import FalAI, Gemini, MiniMax, OpenAI, Replicate, ZhipuAI

__all__ = ["FalAI", "Gemini", "MiniMax", "OpenAI", "Replicate", "ZhipuAI", "load_env"]
