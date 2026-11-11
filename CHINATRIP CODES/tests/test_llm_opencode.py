"""OpenCode Go 网关接线测试（2026-11-11 主力会话模型切换 DeepSeek V4.1 Flash）。

Go 网关硬性要求 x-opencode-session 头（缺了 400 MissingSessionID），且
文档要求客户端自带 UA——两者经 extra_headers 注入，本文件锁住不回归。
"""

import asyncio

import httpx

from app.config import Settings
from app.services.llm import get_flash_adapter, get_llm_adapter
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter


def test_extra_headers_sent_on_every_request():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
                "usage": {},
            },
        )

    adapter = ZhipuGLMAdapter(
        api_key="test",
        base_url="https://example.test/v1",
        model="deepseek-v4.1-flash",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(handler),
        extra_headers={
            "x-opencode-session": "chinatrip",
            "User-Agent": "chinatrip-travel-agent/1.0",
        },
    )
    asyncio.run(adapter.chat([ChatMessage(role="user", content="hi")]))
    assert len(seen) == 1
    assert seen[0].headers["x-opencode-session"] == "chinatrip"
    assert "chinatrip-travel-agent" in seen[0].headers["user-agent"]
    assert seen[0].headers["authorization"] == "Bearer test"


def test_opencode_factory_wires_go_gateway():
    settings = Settings(
        llm_backend="opencode",
        opencode_api_key="oc_sk_test",
        opencode_session_id="chinatrip",
        _env_file=None,
    )
    main = get_llm_adapter(settings)
    flash = get_flash_adapter(settings)
    assert isinstance(main, ZhipuGLMAdapter)
    assert main.base_url == "https://opencode.ai/inference/go/openai/v1"
    assert main.model == "deepseek-v4.1-flash"
    assert main.extra_headers["x-opencode-session"] == "chinatrip"
    # 主链视觉同模型（deepseek-v4.1-flash 吃图入参）；快闪链无视觉。
    assert main.vision_models == ["deepseek-v4.1-flash"]
    assert isinstance(flash, ZhipuGLMAdapter)
    assert flash.model == "deepseek-v4.1-flash"
