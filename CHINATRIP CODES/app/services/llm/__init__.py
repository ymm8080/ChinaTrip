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
from app.services.llm.zhipu import LLMError, LLMQuotaError, ZhipuGLMAdapter

__all__ = [
    "ChatMessage",
    "ChatResult",
    "ExtractResult",
    "LLMAdapter",
    "LLMError",
    "LLMQuotaError",
    "MockLLMAdapter",
    "POICandidate",
    "Settings",
    "ZhipuGLMAdapter",
    "get_llm_adapter",
    "get_flash_adapter",
    "parse_json_content",
    "strip_code_fences",
]


def _opencode_adapter(settings: Settings, *, model: str, vision: bool) -> LLMAdapter:
    """OpenCode Go 网关 = OpenAI-compatible + 两个额外头（会话路由头缺了
    直接 400；UA 自觉声明）。视觉同模型（glm-5.3-flash 吃图入参）。"""
    return ZhipuGLMAdapter(
        api_key=settings.opencode_api_key,
        base_url=settings.opencode_base_url,
        model=model,
        timeout_seconds=settings.glm_timeout_seconds,
        vision_model=model if vision else "glm-4.6v-flash",
        vision_fallback_models=[],
        max_tokens_cap=settings.opencode_max_tokens,
        extra_headers={
            "x-opencode-session": settings.opencode_session_id,
            "User-Agent": "chinatrip-travel-agent/1.0",
        },
    )


def _ark_adapter(settings: Settings, *, model: str, vision: bool) -> LLMAdapter:
    """火山方舟 Plan 网关（OpenAI-compatible，无私有头；2026-11-14 切主力）。

    与 OpenCode Go 同为 OpenAI 协议，直接复用 ZhipuGLMAdapter 的通用客户端。
    视觉同模型（doubao-seed-2-0-pro 支持图入参）。
    """
    return ZhipuGLMAdapter(
        api_key=settings.ark_api_key,
        base_url=settings.ark_base_url,
        model=model,
        timeout_seconds=settings.glm_timeout_seconds,
        vision_model=model if vision else settings.glm_model_vision,
        vision_fallback_models=[],
    )


def get_llm_adapter(settings: Settings) -> LLMAdapter:
    if settings.llm_backend == "mock":
        return MockLLMAdapter()
    if settings.llm_backend == "opencode":
        return _opencode_adapter(settings, model=settings.opencode_model, vision=True)
    if settings.llm_backend == "ark":
        return _ark_adapter(settings, model=settings.ark_model, vision=True)
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
    if settings.llm_backend == "opencode":
        return _opencode_adapter(settings, model=settings.opencode_model, vision=False)
    if settings.llm_backend == "ark":
        return _ark_adapter(settings, model=settings.ark_model, vision=False)
    if settings.llm_backend == "zhipu":
        return ZhipuGLMAdapter(
            api_key=settings.glm_api_key,
            base_url=settings.glm_base_url,
            model=settings.glm_model_flash,
            timeout_seconds=settings.glm_timeout_seconds,
        )
    raise ValueError(f"unknown llm_backend: {settings.llm_backend!r}")
