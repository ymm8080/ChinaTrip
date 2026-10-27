"""LLM 底座锁定测试（用户拍板 2026-10-27：始终 glm-5.3-flash）。

主力与 Flash 分级共用同一模型——分级靠温度/max_tokens 与闸门分流，
不靠换模型；防后续改动悄悄换底座。
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
