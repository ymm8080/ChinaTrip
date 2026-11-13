# -*- coding: utf-8 -*-
"""API 出口无时刻卡过滤回归（2026-11-13 用户拍板「未安排（无时刻灰卡）
不要显示」）：days[].items 中 start_time=None 的非钉 VisitItem 在行程响应
下发层剔除；pinned（铁律 19）与餐/酒店/交通骨架保留；内部清算层的
created/curated/tier≤2 保护名册只保「不删除」不保「下发显示」；
plan.unplaced（「想去」chip 池）与 assumptions 披露原样下发。
"""

from datetime import time as _t
from types import SimpleNamespace

from app.api.plan import _plan_turn_body, _strip_untimed_items
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    UnplacedCandidate,
    VisitItem,
)


def _timed(item_id: str, name: str, **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        city="西安",
        day=1,
        category="museum",
        duration_minutes=120,
        start_time=_t(9, 0),
        end_time=_t(11, 0),
        **kw,
    )


def _untimed(item_id: str, name: str, **kw) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        city="西安",
        day=1,
        category="attraction",
        duration_minutes=120,
        **kw,
    )


def _plan(items) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-strip",
        cities=["西安"],
        days=[DayPlan(day=1, base_city="西安", items=list(items))],
        assumptions=["「钟楼」暂排不上时刻，不删除——暂留原天待重排"],
        unplaced=[
            UnplacedCandidate(
                name="想排没排进的点",
                category="attraction",
                day_hint=1,
                reason="cap",
            )
        ],
    )


def test_strip_removes_untimed_nonpinned_regardless_of_internal_shield():
    """无时刻非钉卡一律剔除——created/curated/tier≤2 豁免只活在内部清算层，
    下发层不再漏出（钟楼博物馆类灰卡从此不上屏）。"""
    plan = _plan(
        [
            _timed("v1", "陕西历史博物馆"),
            _untimed("v2", "普通灰卡"),
            _untimed("v3", "手建灰卡", created=True),
            _untimed("v4", "精选灰卡", curated=True),
            _untimed("v5", "王牌灰卡", tier=1),
        ]
    )
    out = _strip_untimed_items(plan)
    names = [v.name for d in out.days for v in d.items]
    assert names == ["陕西历史博物馆"]


def test_strip_keeps_pinned_untimed():
    """铁律 19：用户钉住的无时刻卡必须留在响应里（钉住是用户铁律）。"""
    plan = _plan([_untimed("v1", "钉住的灰卡", pinned=True)])
    out = _strip_untimed_items(plan)
    assert [v.name for d in out.days for v in d.items] == ["钉住的灰卡"]


def test_strip_keeps_food_hotel_and_transfer():
    """餐/酒店是行程骨架（落地即吃/住），交通 TransferItem 不在过滤范围
    ——无时刻也随行程交付。"""
    plan = _plan(
        [
            VisitItem(
                item_id="m1",
                name="午饭（自由安排）",
                city="西安",
                day=1,
                category="food",
            ),
            VisitItem(
                item_id="h1",
                name="酒店",
                city="西安",
                day=1,
                category="hotel",
            ),
            TransferItem(item_id="t1", day=1, seq=1, from_city="北京", to_city="西安"),
            _untimed("v1", "灰卡"),
        ]
    )
    out = _strip_untimed_items(plan)
    kept = {(type(v).__name__, v.item_id) for d in out.days for v in d.items}
    assert kept == {("VisitItem", "m1"), ("VisitItem", "h1"), ("TransferItem", "t1")}


def test_strip_non_mutating_and_unplaced_preserved():
    """非变异：session.plan 本体不动（内部重排/清算不受影响）；unplaced
    池与 assumptions 披露原样下发（chip 是备选功能，保留不动）。"""
    plan = _plan([_timed("v1", "已排点"), _untimed("v2", "灰卡")])
    out = _strip_untimed_items(plan)
    assert [v.name for d in out.days for v in d.items] == ["已排点"]
    # 本体未被改动
    assert [v.name for d in plan.days for v in d.items] == ["已排点", "灰卡"]
    # unplaced 池与披露原样保留
    assert [c.name for c in out.unplaced] == ["想排没排进的点"]
    assert out.assumptions == plan.assumptions
    # 已排卡对象共享（浅拷贝壳，不 deep-copy 条目）
    assert out.days[0].items[0] is plan.days[0].items[0]


def test_plan_turn_body_exit_strips(monkeypatch):
    """出口接线：_plan_turn_body（GET session / message / pin 等一族端点
    的统一响应组装）下发的 plan 不含无时刻非钉卡；pinned 与 unplaced
    保留。"""
    monkeypatch.setattr("app.api.plan._plan_with_alternatives", lambda p: p)
    monkeypatch.setattr("app.api.plan.current_violations", lambda s: [])
    session = SimpleNamespace(
        state="ready",
        plan=_plan(
            [
                _timed("v1", "已排点"),
                _untimed("v2", "灰卡"),
                _untimed("v3", "钉住灰卡", pinned=True),
            ]
        ),
        assumptions=[],
        pending_sites=[],
        pending_restos=[],
    )
    body = _plan_turn_body(session, "reply", None)
    names = [v.name for d in body["plan"].days for v in d.items]
    assert names == ["已排点", "钉住灰卡"]
    assert [c.name for c in body["plan"].unplaced] == ["想排没排进的点"]
