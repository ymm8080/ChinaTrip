# -*- coding: utf-8 -*-
"""R39b（2026-11-25 用户「一个晚餐或者一个午餐，可能有一个自由卡加一个
餐厅并排嘛」）。

根因：读路径 heal_arrival_light 调 _ensure_meal_cards 补卡后没跑占位吸收；
旧会话里命名餐卡被编辑漂到另一餐段（item_id 仍叫 meal-lunch-N，时刻已是
17:39=晚餐），_ensure_meal_cards 按 id 槽补「晚饭」自由卡 → 与真餐厅并排。

覆盖：
1. 同槽自由卡被撤（时刻口径判槽，不看 item_id 的槽标签）；
2. 不同槽的自由卡保留（午餐真餐 + 晚餐自由，属正常）；
3. 幂等——重复调用不再改动；
4. 无真餐的自由卡保留。
"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import _absorb_free_card_beside_named
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem


def _named(iid: str, name: str, at: str):
    h, m = (int(x) for x in at.split(":"))
    return VisitItem(
        item_id=iid,
        name=name,
        category="food",
        city="北京",
        poi_id="p1",
        start_time=time(h, m),
        end_time=time(h + 1, m),
        duration_minutes=60,
        day=1,
    )


def _free(iid: str, name: str, at: str):
    h, m = (int(x) for x in at.split(":"))
    return VisitItem(
        item_id=iid,
        name=name,
        category="food",
        city="北京",
        poi_id=None,
        start_time=time(h, m),
        end_time=time(h + 1, m),
        duration_minutes=60,
        day=1,
    )


def _plan(*items) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="t",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )


def test_absorbs_free_card_when_named_drifted_into_its_slot():
    # 命名卡 item_id 叫 lunch 但时刻已是晚餐 17:39；自由卡「晚饭」同槽。
    plan = _plan(
        _named("meal-lunch-2", "宫宴·宋韵", "17:39"),
        _free("meal-dinner-2", "晚饭", "17:29"),
    )
    dropped = _absorb_free_card_beside_named(plan)
    assert dropped == ["第1天晚饭"]
    assert [i.item_id for i in plan.days[0].items] == ["meal-lunch-2"]


def test_keeps_free_card_in_other_slot():
    plan = _plan(
        _named("meal-lunch-1", "万丽轩", "12:00"),
        _free("meal-dinner-1", "晚饭", "18:00"),
    )
    assert _absorb_free_card_beside_named(plan) == []
    assert len(plan.days[0].items) == 2


def test_idempotent():
    plan = _plan(
        _named("meal-dinner-1", "白家大院", "19:43"),
        _free("meal-dinner-1-free", "晚饭", "19:12"),
    )
    assert len(_absorb_free_card_beside_named(plan)) == 1
    assert _absorb_free_card_beside_named(plan) == []
    assert len(plan.days[0].items) == 1


def test_keeps_free_card_without_named():
    plan = _plan(_free("meal-lunch-1", "午餐", "12:00"))
    assert _absorb_free_card_beside_named(plan) == []
    assert len(plan.days[0].items) == 1
