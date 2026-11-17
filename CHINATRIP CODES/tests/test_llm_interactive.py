# -*- coding: utf-8 -*-
"""LLM 随时可交互（2026-11-17 用户二拍修正）：
「如果信息不全 LLM 可以或者说应该向用户提问，谁说不能提问。PLANNING
ENGINE 应该可以随时交互」+「问用户前先查库是对的。还有如果有与客户说的
不一致，猜出大概也需要跟用户确认」。

契约三层：
①先查底库——能自己定的不问（城市推断等确定性通道负责）；
②缺了直接问——编辑通道 reply 里的问句原样到用户面前（不再剥问句）；
③猜想要确认——近似匹配/推断的结果必须点名请用户确认
（确认卡提案披露 + 系统提示词③ + 城市推断确认式措辞）。
"""

import asyncio
import json
import os

import pytest

from app.services.agent.plan import (
    _EDIT_SYSTEM_PROMPT,
    PlanningAgent,
)
from app.services.llm.base import ChatResult


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _llm_select_mode():
    # 与 test_plan_agent 同口径：v0 走 LLM 选点，脚本第一发 v0_reply 被
    # start 消费，后续才是编辑轮抽签。
    os.environ["PLAN_SELECT_MODE"] = "llm"
    yield
    os.environ.pop("PLAN_SELECT_MODE", None)


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
    return json.dumps({"reply": reply, "diffs": diffs}, ensure_ascii=False)


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


def test_edit_reply_question_passes_through_diff_lands():
    # 信息不全时 LLM 直接问用户：问句原样到用户面前，diff 照常落地
    llm = ScriptedLLM(
        [
            v0_reply(_ITEMS),
            edit_reply(
                "已删除。请问您是想把豫园也一起删掉，还是保留？",
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
    # 问句保留（引擎随时可交互）
    assert "豫园" in reply and ("？" in reply or "?" in reply)
    assert change is not None
    assert all(i.item_id != "v1" for d in session.plan.days for i in d.items)


def test_edit_question_only_reply_surfaces_to_user():
    # 纯提问轮（无 diff）：问题原样返回给用户——这就是「随时交互」
    llm = ScriptedLLM(
        [
            v0_reply(_ITEMS),
            edit_reply("您想删掉哪一天的外滩呢？", []),
        ]
    )
    agent = PlanningAgent(llm)
    session = run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="博物馆")
    )
    session, reply, change = run(agent.message(session, "删掉外滩"))
    assert llm.calls == 2
    assert "外滩" in reply and "？" in reply
    assert change is None


def test_edit_system_prompt_check_first_then_ask_and_confirm():
    # 先查库 → 缺了问 → 猜测/近似必须确认；一刀切禁问的措辞已撤
    assert "先查底库" in _EDIT_SYSTEM_PROMPT
    assert "向用户" in _EDIT_SYSTEM_PROMPT and "确认" in _EDIT_SYSTEM_PROMPT
    assert "绝不出现任何问句" not in _EDIT_SYSTEM_PROMPT
    assert "NO LLM CAN ASK" not in _EDIT_SYSTEM_PROMPT
    # need_clarification 死通道保持删除（提问走 reply 文本，引擎可见）
    assert "need_clarification" not in _EDIT_SYSTEM_PROMPT


def test_strip_helper_removed():
    # 一刀切禁问的硬闸已删除（不允许再被接回 chokepoint）
    import app.services.agent.plan as plan_mod

    assert not hasattr(plan_mod, "_strip_llm_questions")
