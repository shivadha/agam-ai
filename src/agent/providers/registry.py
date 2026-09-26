"""
registry.py — maps provider ids to plugin classes.
"""
from __future__ import annotations

from .base import FreeWebProvider
from .gemini import GeminiProvider
from .veo import VeoProvider
from .chatgpt import ChatGPTProvider
from .hailuo import HailuoProvider

_REGISTRY: dict[str, type[FreeWebProvider]] = {
    "gemini_web": GeminiProvider,
    "veo_web": VeoProvider,
    "chatgpt_go": ChatGPTProvider,
    "hailuo_web": HailuoProvider,
}


def get_provider(provider_id: str) -> FreeWebProvider:
    cls = _REGISTRY.get(provider_id)
    if cls is None:
        raise KeyError(f"unknown free-web provider: {provider_id!r} "
                       f"(known: {sorted(_REGISTRY)})")
    return cls()


def known_providers() -> list[str]:
    return sorted(_REGISTRY)
