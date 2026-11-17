# -*- coding: utf-8 -*-
"""NO LLM QUESTIONS（2026-11-17 用户拍板「NO LLM CAN ASK ANY QUESTIONS TO
GATHER NECESSARY INFORMATION」+「city 只是例子——底库能查到的信息先内部查，
查不到才问用户」）。

编辑通道（_apply_conversation）是唯一面向用户的 LLM 自由文本出口：
- reply 里出现任何问句 → 整句剥掉（_strip_llm_questions）；
- 问句-only 的抽签按空回复走重采样，提问漏不到用户面前；
- 系统提示词同步禁问（need_clarification 通道删除，2026-10-31 的
  「允许问偏好类选择问题」裁废——缺信息一律先查底库/会话，剩下由
  确定性澄清轮问）。
"""

import asyncio
import json
import os

import pytest

from app.services.agent.plan import (
    _EDIT_SYSTEM_PROMPT,
    PlanningAgent,
    _strip_llm_questions,
)
from app.services.llm.base import ChatResult


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _llm_select_mode():
    # 编辑通道测试与 test_plan_agent 同口径：v0 走 LLM 选点，脚本第
    # 一发 v0_reply 被 start 消费，后续才是编辑轮抽签。
    os.environ["PLAN_SELECT_MODE"] = "llm"
    yield
    os.environ.pop("PLAN_SELECT_MODE", None)


# --- ① 问句剥离 -------------------------------------------------------------


def test_strip_removes_question_sentences():
    assert (
        _strip_llm_questions("已把博物馆移到第2天。要不要顺便把餐厅也调整一下？")
        == "已把博物馆移到第2天。"
    )
    assert (
        _strip_llm_questions("想换基地吗？都江堰熊猫谷可替换。")
        == "都江堰熊猫谷可替换。"
    )
    # 整句都是问句 → 空串（调用方按空回复走重采样/兜底）
    assert _strip_llm_questions("需要我帮你调整哪一天？") == ""
    assert _strip_llm_questions("Want me to also change dinner?") == ""
    # 没有问句原样返回
    clean = "已删除外滩，行程已更新。"
    assert _strip_llm_questions(clean) == clean
    assert _strip_llm_questions("") == ""
    done = "All done - moved to day 2!"
    assert _strip_llm_questions(done) == done


# --- ② 编辑通道出口守卫 ------------------------------------------------------


class ScriptedLLM:
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        self.calls += 1
        return ChatResult(content=self.replies.pop(0), model="scripted")


def v0_reply(items, assumptions=None) -> str:
    return json.dumps(
        {"items": items, "assumptions": assumptions or []}, ensure_ascii=False
    )


def edit_reply(reply: str, diffs) -> str:
    return json.dumps(
        {"reply": reply, "diffs": diffs, "need_clarification": []},
        ensure_ascii=False,
    )


_ITEMS = [
    {
        "name": "外滩",
        "city": "上海",
        "category": "sight",
        "day": 1,
        "duration_minutes": 90,
    },
    {
        "name": "豫园",
        "city": "上海",
        "category": "sight",
        "day": 1,
        "duration_minutes": 60,
    },
]


def test_edit_reply_question_sentence_stripped_diff_still_lands():
    # LLM 说明里夹带问句（2026-10-31 旧裁允许的「倾向去哪个基地？」类）
    # → 问句整句剥掉，diff 照常落地。
    llm = ScriptedLLM(
        [
            v0_reply(_ITEMS),
            edit_reply(
                "已删除。要不要我把豫园也删掉？",
                [{"op": "remove", "item_id": "v1"}],
            ),
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="博物馆")
    )
    session, reply, change = run(agent.message(session, "删掉外滩"))
    assert "已删除" in reply
    assert "？" not in reply and "?" not in reply
    assert change is not None
    assert all(i.item_id != "v1" for d in session.plan.days for i in d.items)


def test_edit_question_only_reply_resamples_never_surfaces_question():
    # 抽签 1 只有问句、没有 diffs → 按空回复重采样；抽签 2 落地。
    llm = ScriptedLLM(
        [
            v0_reply(_ITEMS),
            edit_reply("你想删掉哪一个景点呢？", []),
            edit_reply("已删除", [{"op": "remove", "item_id": "v1"}]),
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="博物馆")
    )
    session, reply, change = run(agent.message(session, "删掉外滩"))
    # LLM_ATTEMPTS=2：问句-only 抽签按空回复重采样一次即落地，
    # 提问没有漏到用户面前。
    assert llm.calls == 3
    assert "？" not in reply and "?" not in reply
    assert "你想删掉哪一个景点呢" not in reply
    assert "已删除" in reply
    assert change is not None


def test_edit_system_prompt_bans_questions():
    # 系统提示词禁问 + need_clarification 通道已从 schema 里删除
    assert "NO LLM CAN ASK ANY QUESTIONS" in _EDIT_SYSTEM_PROMPT
    assert "need_clarification" not in _EDIT_SYSTEM_PROMPT
    assert "允许问偏好类选择问题" not in _EDIT_SYSTEM_PROMPT
