"""LLM 底座锁定测试（用户拍板 2026-10-27：始终 glm-5.3-flash）。

主力与 Flash 分级共用同一模型——分级靠温度/max_tokens 与闸门分流，
不靠换模型；防后续改动悄悄换底座。2026-11-14 起 OpenCode 网关的默认
模型也钉在同一底座（.env 可覆盖，但仓库默认必须是 glm-5.3-flash）。
"""

from app.config import Settings
from app.services.llm import get_flash_adapter, get_llm_adapter


def test_settings_pin_glm_5_3_flash():
    settings = Settings()
    assert settings.glm_model == "glm-5.3-flash"
    assert settings.glm_model_flash == "glm-5.3-flash"


def test_zhipu_adapters_both_tiers_use_pinned_model():
    settings = Settings(llm_backend="zhipu", glm_api_key="k")
    assert get_llm_adapter(settings).model == "glm-5.3-flash"
    assert get_flash_adapter(settings).model == "glm-5.3-flash"


def test_opencode_default_model_is_pinned_too():
    """新环境/CI 不依赖本地 .env：仓库默认 OpenCode 模型即 glm-5.3-flash。"""
    settings = Settings(llm_backend="opencode", _env_file=None)
    assert settings.opencode_model == "glm-5.3-flash"
    assert get_llm_adapter(settings).model == "glm-5.3-flash"
    assert get_flash_adapter(settings).model == "glm-5.3-flash"
