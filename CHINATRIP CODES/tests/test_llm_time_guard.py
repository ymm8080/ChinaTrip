# -*- coding: utf-8 -*-
"""PR3 回归：LLM 时间戳守卫（用户原话时刻照抄钉住；发明时刻→时段偏好
+解钉交排程器）。"""

from datetime import time

from app.services.agent.plan import (
    PlanningAgent,
    _guard_llm_times,
    _user_stated_times,
)
from app.services.itinerary.models import DiffOp, VisitItem


def _v(item_id, *, start=None, dur=60, day=1, pinned=False, bvt=None):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city="西安",
        day=day,
        duration_minutes=dur,
        start_time=start,
        pinned=pinned,
        best_visit_time=bvt,
    )


# ---------- 用户时刻抽取 ----------


def test_user_stated_times_formats():
    assert _user_stated_times("改到 10:00 开始") == {"10:00"}
    assert _user_stated_times("10点半集合") == {"10:30"}
    assert _user_stated_times("10点30分") == {"10:30"}
    assert _user_stated_times("10点走") == {"10:00"}
    assert _user_stated_times("9:05 出发") == {"09:05"}
    assert _user_stated_times("第2天下午再逛") == set()
    assert _user_stated_times("三天两晚") == set()
    # 中文数字时刻（selfrepair 用例原话形态）
    assert _user_stated_times("西湖改到九点开始") == {"09:00"}
    assert _user_stated_times("晚上九点出发") == {"21:00"}
    assert _user_stated_times("十点半集合") == {"10:30"}
    assert _user_stated_times("下午三点半到") == {"15:30"}


# ---------- 守卫 ----------


def test_guard_keeps_user_stated_time():
    op = DiffOp(op="retime", item_id="v1", new_start_time=time(10, 0))
    kept, hints = _guard_llm_times([op], "把西湖改到 10:00 开始")
    assert kept == [op] and hints == []


def test_guard_strips_invented_retime_to_window():
    op = DiffOp(op="retime", item_id="v1", new_start_time=time(14, 0))
    kept, hints = _guard_llm_times([op], "把西湖挪到下午")
    assert kept == [] and hints == [("v1", "afternoon")]


def test_guard_move_keeps_day_strips_invented_time():
    op = DiffOp(op="move", item_id="v1", new_day=2, new_start_time=time(9, 30))
    kept, hints = _guard_llm_times([op], "西湖挪到第二天")
    assert len(kept) == 1 and kept[0].op == "move"
    assert kept[0].new_day == 2 and kept[0].new_start_time is None
    assert hints == [("v1", "morning")]


def test_guard_leaves_other_ops_alone():
    ops = [
        DiffOp(op="remove", item_id="v1"),
        DiffOp(op="move", item_id="v2", new_day=2),  # 无时刻：透传
    ]
    kept, hints = _guard_llm_times(ops, "随便")
    assert kept == ops and hints == []


def test_guard_user_time_with_chinese_half():
    op = DiffOp(op="retime", item_id="v1", new_start_time=time(10, 30))
    kept, hints = _guard_llm_times([op], "十点半…不对，10点半出发")
    assert kept == [op] and hints == []


# ---------- 流程级：发明时刻被转成时段偏好+解钉 ----------


class _ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)

    async def chat(self, messages, temperature=0.2):

        from app.services.llm.base import ChatResult

        return ChatResult(content=self.replies.pop(0))


def test_flow_invented_retime_becomes_window_hint():
    import asyncio
    import json

    v0 = json.dumps(
        {
            "items": [
                {"i": 1, "day": 1, "duration_minutes": 90, "reason": "r"},
            ],
            "assumptions": [],
        },
        ensure_ascii=False,
    )
    agent = PlanningAgent(_ScriptedLLM([v0]))
    session = asyncio.run(
        agent.start(device_id="d1", cities=["西安"], days=1, preferences="随便")
    )
    target = next(i for i in session.plan.days[0].items if isinstance(i, VisitItem))
    target.pinned = True
    # item_id 用 f-string 注入（json.dumps(None) 产 null，replace None 不命中）
    edit = (
        '{"reply": "已调整", "diffs": ['
        f'{{"op": "retime", "item_id": "{target.item_id}", '
        '"new_start_time": "14:00"}]}'
    )
    agent._llm.replies.append(edit)

    session, reply, _ = asyncio.run(agent.message(session, "这个点挪到下午吧"))

    item = next(
        i
        for i in session.plan.days[0].items
        if isinstance(i, VisitItem) and i.item_id == target.item_id
    )
    # 发明的 14:00 不照抄：条目不钉、带下午时段偏好、由排程器落位
    assert item.pinned is False
    assert item.best_visit_time == "afternoon"
