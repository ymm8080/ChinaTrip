"""LLM adapters + factory."""

from app.config import Settings
from app.services.llm.base import (
    ChatMessage,
    ChatResult,
    ExtractResult,
    LLMAdapter,
    POICandidate,
    parse_json_content,
    strip_code_fences,
)
from app.services.llm.mock import MockLLMAdapter
from app.services.llm.zhipu import LLMError, ZhipuGLMAdapter

__all__ = [
    "ChatMessage",
    "ChatResult",
    "ExtractResult",
    "LLMAdapter",
    "LLMError",
    "MockLLMAdapter",
    "POICandidate",
    "Settings",
    "ZhipuGLMAdapter",
    "get_llm_adapter",
    "get_flash_adapter",
    "parse_json_content",
    "strip_code_fences",
]


def get_llm_adapter(settings: Settings) -> LLMAdapter:
    if settings.llm_backend == "mock":
        return MockLLMAdapter()
    if settings.llm_backend == "zhipu":
        return ZhipuGLMAdapter(
            api_key=settings.glm_api_key,
            base_url=settings.glm_base_url,
            model=settings.glm_model,
            timeout_seconds=settings.glm_timeout_seconds,
            vision_model=settings.glm_model_vision,
            vision_fallback_models=[
                m for m in settings.glm_vision_fallback_models.split(",") if m.strip()
            ],
        )
    raise ValueError(f"unknown llm_backend: {settings.llm_backend!r}")


def get_flash_adapter(settings: Settings) -> LLMAdapter:
    """Flash-tier adapter for the fast lane (design §6.12 gate/translate)."""
    if settings.llm_backend == "mock":
        return MockLLMAdapter()
    if settings.llm_backend == "zhipu":
        return ZhipuGLMAdapter(
            api_key=settings.glm_api_key,
            base_url=settings.glm_base_url,
            model=settings.glm_model_flash,
            timeout_seconds=settings.glm_timeout_seconds,
        )
    raise ValueError(f"unknown llm_backend: {settings.llm_backend!r}")
