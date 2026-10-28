"""选点 LLM 瘦身与预算门禁（2026-10-28 ReadTimeout 收口）。

覆盖：候选池上限（餐饮锚点全保/premium 加权/城市均衡/确定性）、索引式
输出回填（名称/城市/品类/时长）、旧版 name 输出兼容、超时重试砍半候选
池、预算耗尽跳过重试直接降级、新 kwargs 仅对支持的适配器下发。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace

from app.services.agent.plan import (
    SELECT_MAX_TOKENS,
    SELECT_TIMEOUT_SECONDS,
    PlanningAgent,
)
from app.services.llm import LLMError
from app.services.llm.base import ChatResult


def _cand(i: int, city: str, *, rating=4.5, count=10000, cat="sight", tags=None):
    return {
        "name": f"{city}景点{i:02d}",
        "city": city,
        "category": cat,
        "rating": rating,
        "rating_count": count,
        "tags": tags or [],
    }


def _shim(llm):
    return SimpleNamespace(_llm=llm, _coerce_v0_items=PlanningAgent._coerce_v0_items)


def _select(llm, pool, days=1):
    return asyncio.run(PlanningAgent._select_pois(_shim(llm), pool, days, "", {}, None))


class ScriptedSelectLLM:
    """新签名 fake：记录收到的 kwargs 与 messages，按脚本应答或抛错。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.kwargs_log: list[dict] = []
        self.messages_log: list[list] = []

    async def chat(
        self,
        messages,
        *,
        temperature=0.3,
        max_tokens=None,
        thinking=None,
        timeout_seconds=None,
    ) -> ChatResult:
        self.kwargs_log.append(
            {
                "temperature": temperature,
                "max_tokens": max_tokens,
                "thinking": thinking,
                "timeout_seconds": timeout_seconds,
            }
        )
        self.messages_log.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(content=reply, model="scripted", tokens_in=10, tokens_out=5)


class LegacyLLM:
    """旧签名 fake：证明新 kwargs 不会下发给不支持的适配器。"""

    def __init__(self, reply):
        self.reply = reply
        self.called = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None) -> ChatResult:
        self.called += 1
        return ChatResult(content=self.reply, model="legacy")


def test_select_index_output_maps_back():
    pool = [_cand(i, "成都", rating=4.0 + i / 100) for i in range(12)]
    pool[3]["suggested_duration_min"] = 90
    reply = json.dumps(
        {
            "items": [
                {"i": 1, "day": 1},
                {"i": 3, "day": 2, "duration_minutes": 45},
            ],
            "assumptions": [],
        },
        ensure_ascii=False,
    )
    llm = ScriptedSelectLLM([reply])
    items, _extra, ok = _select(llm, pool, days=2)
    assert ok
    assert [it["name"] for it in items] == [pool[1]["name"], pool[3]["name"]]
    # 城市/品类按序号回填
    assert items[0]["city"] == "成都"
    assert items[0]["category"] == "sight"
    # 显式时长保留；缺省时长回 60（有库建议时长时由后处理替换）
    assert items[1]["duration_minutes"] == 45
    assert items[0]["duration_minutes"] == 60
    # 新 kwargs 只下发给支持的适配器
    kw = llm.kwargs_log[0]
    assert kw["thinking"] is False
    assert kw["timeout_seconds"] == SELECT_TIMEOUT_SECONDS
    assert kw["max_tokens"] == SELECT_MAX_TOKENS
    # listing 行首带序号（索引对齐的根）
    user = llm.messages_log[0][-1].content
    assert "- 0|成都景点00（" in user


def test_select_legacy_name_output_still_works():
    pool = [_cand(i, "成都") for i in range(5)]
    reply = json.dumps(
        {
            "items": [
                {"name": pool[2]["name"], "city": "成都", "category": "sight", "day": 1}
            ],
            "assumptions": [],
        },
        ensure_ascii=False,
    )
    llm = LegacyLLM(reply)
    items, _extra, ok = _select(llm, pool)
    assert ok and llm.called == 1
    assert items[0]["name"] == pool[2]["name"]


def test_select_retry_halves_pool():
    pool = [_cand(i, "成都") for i in range(20)]
    good = json.dumps({"items": [{"i": 0, "day": 1}], "assumptions": []})
    llm = ScriptedSelectLLM([LLMError("zhipu request timeout: ReadTimeout"), good])
    items, _extra, ok = _select(llm, pool)
    assert ok
    assert len(llm.messages_log) == 2
    user2 = llm.messages_log[1][-1].content
    # 20 → 砍半 10 条，且行首序号重新从 0 对齐
    assert user2.count("|成都景点") == 10
    assert "- 0|成都景点00（" in user2
    assert items[0]["name"] == pool[0]["name"]


def test_select_budget_skips_retry(monkeypatch):
    monkeypatch.setattr("app.services.agent.plan.SELECT_BUDGET_SECONDS", 0.5)
    good = json.dumps({"items": [{"i": 0, "day": 1}], "assumptions": []})
    llm = ScriptedSelectLLM([LLMError("zhipu request timeout: ReadTimeout"), good])
    items, _extra, ok = _select(llm, [_cand(i, "成都") for i in range(20)])
    assert not ok and items == []
    # 预算耗尽：第一次超时后不再发起新尝试
    assert len(llm.messages_log) == 1


def test_index_out_of_range_falls_back_to_retry():
    pool = [_cand(i, "成都") for i in range(6)]
    good = json.dumps(
        {"items": [{"name": pool[1]["name"], "day": 1}], "assumptions": []},
        ensure_ascii=False,
    )
    llm = ScriptedSelectLLM([json.dumps({"items": [{"i": 99, "day": 1}]}), good])
    items, _extra, ok = _select(llm, pool)
    assert ok and items[0]["name"] == pool[1]["name"]
    assert len(llm.messages_log) == 2


def test_new_kwargs_absent_on_legacy_signature():
    """inspect 探针只对声明了参数的适配器下发新 kwargs。"""
    params = inspect.signature(LegacyLLM(None).chat).parameters
    assert "thinking" not in params and "timeout_seconds" not in params
    params2 = inspect.signature(ScriptedSelectLLM([]).chat).parameters
    assert "thinking" in params2 and "timeout_seconds" in params2
