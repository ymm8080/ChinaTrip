"""zhipu 适配器配额死（code 1310 + 恢复戳）fail-fast 测试。

事故 2026-11-11：账户额度死到未来时间点，_post_json 的 2s/4s spaced
retry 纯属浪费——整段对话轮次被拖到超时且回复只说「请再发一次」。
窗口内应直接抛 LLMQuotaError（带恢复时间），窗口外/无戳维持旧重试。
全部走 httpx.MockTransport，不联网。
"""

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest

from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import LLMError, LLMQuotaError, ZhipuGLMAdapter


def _adapter(handler, calls: list) -> ZhipuGLMAdapter:
    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return ZhipuGLMAdapter(
        api_key="test",
        base_url="https://example.test",
        model="glm-test",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(counting),
    )


def _quota_body(recover_at: str) -> dict:
    return {
        "error": {
            "code": "1310",
            "message": f"用户已达到每秒/每日使用限额，额度将在 {recover_at} 恢复。",
        }
    }


def test_quota_dead_fails_fast_with_recover_at():
    future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=_quota_body(future))

    adapter = _adapter(handler, calls)
    with pytest.raises(LLMQuotaError) as exc_info:
        asyncio.run(adapter.chat([ChatMessage(role="user", content="hi")]))
    assert exc_info.value.recover_at == future
    assert "http status 429" in str(exc_info.value)  # 视觉链子串兼容
    assert len(calls) == 1  # fail fast：一次 POST 即抛，不重试


def test_quota_window_lapsed_retries_like_plain_429():
    past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=_quota_body(past))

    adapter = _adapter(handler, calls)
    with pytest.raises(LLMError) as exc_info:
        asyncio.run(adapter.chat([ChatMessage(role="user", content="hi")]))
    assert not isinstance(exc_info.value, LLMQuotaError)
    assert len(calls) == 3  # 窗口已过——维持旧 spaced retry


def test_plain_429_without_quota_body_retries():
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "1113", "message": "其他"}})

    adapter = _adapter(handler, calls)
    with pytest.raises(LLMError) as exc_info:
        asyncio.run(adapter.chat([ChatMessage(role="user", content="hi")]))
    assert not isinstance(exc_info.value, LLMQuotaError)
    assert len(calls) == 3
