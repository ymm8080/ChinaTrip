# -*- coding: utf-8 -*-
"""一句话加心愿的确定性落位（2026-11-13 延迟收口）。

用户口径：「一句话说要去哪，就该查坐标→归簇→定日→落位，不该等一分钟」。
本文件锁三件事：
1. 单点口吻解析（多点/带其它动作/疑问句不接管，交主车道）；
2. 落位规则（同簇归日、就近插位、装不下按档号+距离让位）；
3. 快路径零 LLM：try_fast_wish 成功时一次模型调用都不发。
"""

from __future__ import annotations

import asyncio
from datetime import time as _time

from app.services.agent.plan import PlanSession
from app.services.agent.wish_fast import (
    parse_place_request,
    place_food,
    place_hotel,
    place_wish,
    try_fast_wish,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 上海实测锚点（活库坐标）
_YUYUAN = GeoPoint(lon=121.4913, lat=31.2271)  # 豫园（外滩簇）
_BUND = GeoPoint(lon=121.4900, lat=31.2400)  # 外滩
_NANJING = GeoPoint(lon=121.4737, lat=31.2354)  # 南京东路
_DISNEY = GeoPoint(lon=121.6670, lat=31.1440)  # 迪士尼（远簇）


def _visit(
    name: str,
    location: GeoPoint,
    day: int,
    *,
    dur: int = 90,
    tier: int = 8,
    category: str = "sight",
    pinned: bool = False,
) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="上海",
        day=day,
        duration_minutes=dur,
        location=location,
        category=category,
        tier=tier,
        pinned=pinned,
    )


def _plan(day_items: dict[int, list[VisitItem]]) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-fast-wish",
        cities=["上海"],
        days=[
            DayPlan(day=no, base_city="上海", items=list(items))
            for no, items in day_items.items()
        ],
    )


def _poi(name: str = "豫园", location: GeoPoint = _YUYUAN, minutes: int = 90) -> dict:
    return {
        "source_poi_id": "ct_上海_4",
        "name": name,
        "city": "上海",
        "category": "park",
        "tags": ["lp", "intl"],
        "address": "上海市黄浦区豫园街道",
        "opening_hours": "周二至周日 09:00-16:30",
        "source": "amap",
        "location": [location.lon, location.lat],
        "suggested_duration_min": minutes,
    }


# --- 1. 口吻解析 -----------------------------------------------------------


def test_parse_place_request_shapes():
    assert parse_place_request("我要去豫园") == "豫园"
    assert parse_place_request("我想去豫园吧") == "豫园"
    assert parse_place_request("去豫园") == "豫园"
    assert parse_place_request("加豫园") == "豫园"
    assert parse_place_request("把豫园加到行程") == "豫园"
    assert parse_place_request("我想吃南翔馒头店") == "南翔馒头店"
    assert parse_place_request("我要住和平饭店") == "和平饭店"
    assert parse_place_request("I want to go to Yu Garden") == "Yu Garden"
    assert parse_place_request("add Yu Garden to my trip") == "Yu Garden"


def test_parse_place_request_rejects_non_single_place():
    # 多点/带别的动作/带天数/疑问句：交主车道（宁可慢不可错）
    assert parse_place_request("我要去豫园和外滩") is None
    assert parse_place_request("我要去豫园，顺便吃南翔小笼") is None
    assert parse_place_request("把豫园挪到第三天") is None
    assert parse_place_request("豫园几点开门") is None
    assert parse_place_request("我想去上海玩三天") is None
    assert parse_place_request("帮我规划一下上海三日游") is None


def _night_card(day: int) -> VisitItem:
    return VisitItem(
        item_id=f"hotel-night-d{day}",
        name="🏨 回酒店·夜间休息",
        city="上海",
        day=day,
        category="hotel",
        duration_minutes=60,
        start_time=_time(20, 0),
        end_time=_time(21, 0),
        soft_pin=True,
    )


# --- 2. 落位规则 -----------------------------------------------------------


def test_place_wish_joins_the_nearest_cluster_day():
    plan = _plan(
        {
            1: [_visit("外滩", _BUND, 1, tier=2), _visit("南京东路", _NANJING, 1)],
            2: [_visit("上海迪士尼", _DISNEY, 2)],
        }
    )
    placement = place_wish(plan, name="豫园", poi=_poi(), city="上海", item_id="v-new")
    assert placement is not None
    assert placement.day == 1  # 外滩簇，不是迪士尼日
    placed = next(
        i for d in placement.plan.days for i in d.items if i.item_id == "v-new"
    )
    assert placed.poi_id == "ct_上海_4"
    assert placed.start_time is not None  # 有具体时刻
    # 就近插位：排在离它最近的外滩/南京东路之后（不是队尾）
    day1 = next(d for d in placement.plan.days if d.day == 1)
    order = [i.item_id for i in day1.items]
    assert order.index("v-new") <= 2
    # 原计划不被就地修改（调用方确认后才写回）
    assert all(i.item_id != "v-new" for d in plan.days for i in d.items)


def test_place_wish_evicts_lowest_priority_far_item():
    # 一天快满：5 张 130 分钟卡 + 腿 ≈ 700 分钟，再塞 90 分钟就装不下——
    # 其中 tier11 的那张还离新点最远，按「档号大=弱、远者先走」让位。
    fills = [
        _visit("5A甲", _BUND, 1, dur=130, tier=2),
        _visit("5A乙", _NANJING, 1, dur=130, tier=2),
        _visit("4A丙", GeoPoint(lon=121.45, lat=31.22), 1, dur=130, tier=8),
        _visit("街区丁", GeoPoint(lon=121.44, lat=31.21), 1, dur=130, tier=9),
        _visit("长尾戊", GeoPoint(lon=121.60, lat=31.30), 1, dur=130, tier=11),
    ]
    plan = _plan({1: fills, 2: [_visit("迪士尼", _DISNEY, 2)]})
    placement = place_wish(plan, name="豫园", poi=_poi(), city="上海", item_id="v-new")
    assert placement is not None
    assert placement.removed, "塞满的一天应让位至少一张低档卡"
    victim = placement.removed[0]
    assert victim.tier == 11
    placed = next(
        i for d in placement.plan.days for i in d.items if i.item_id == "v-new"
    )
    assert placed.start_time is not None
    # 让位留痕：进 unplaced（H5 可替换 chips），不静默蒸发
    assert any(u.name == victim.name for u in placement.plan.unplaced)
    # 高档卡一张不动
    names = {i.name for d in placement.plan.days for i in d.items}
    assert {"5A甲", "5A乙"} <= names


def test_place_wish_never_evicts_pinned_or_must_items():
    # 满日 + 低档卡是钉的/必去的：让位不能动它们（宁可交主车道也不破铁律 19）
    fills = [
        _visit("5A甲", _BUND, 1, dur=130, tier=2, pinned=True),
        _visit("5A乙", _NANJING, 1, dur=130, tier=2),
        _visit("4A丙", GeoPoint(lon=121.45, lat=31.22), 1, dur=130, tier=8),
        _visit("长尾戊", GeoPoint(lon=121.60, lat=31.30), 1, dur=130, tier=11),
        _visit("长尾己", GeoPoint(lon=121.62, lat=31.31), 1, dur=130, tier=11),
    ]
    fills[2].must = True
    plan = _plan({1: fills})
    placement = place_wish(plan, name="豫园", poi=_poi(), city="上海", item_id="v-new")
    assert placement is not None
    removed = {i.name for i in placement.removed}
    assert "5A甲" not in removed  # 钉
    assert "4A丙" not in removed  # 必去


def test_place_hotel_fills_the_hotel_cards():
    # 2026-11-13 用户拍板：酒店心愿→HOTEL 卡（整段住宿铺开）
    plan = _plan(
        {
            1: [_visit("外滩", _BUND, 1), _night_card(1)],
            2: [
                _visit("田子坊", GeoPoint(lon=121.4690, lat=31.2087), 2),
                _night_card(2),
            ],
        }
    )
    poi = {
        "name": "上海和平饭店",
        "city": "上海",
        "category": "hotel",
        "source_poi_id": "ct_上海_999",
        "address": "南京东路20号",
        "location": [121.4901, 31.2394],
    }
    placement = place_hotel(plan, name="和平饭店", poi=poi)
    assert placement is not None
    assert placement.kind == "hotel"
    nights = [
        i
        for d in placement.plan.days
        for i in d.items
        if i.item_id.startswith("hotel-night")
    ]
    assert nights and all(i.name == "上海和平饭店" for i in nights)
    assert placement.synced_cards >= 1
    assert placement.item.address == "南京东路20号"


def test_place_food_fills_the_meal_card():
    # 2026-11-13 用户拍板：餐饮心愿→午/晚餐卡（餐窗锚定，不占景点位）
    from app.services.agent.plan import PlanningAgent

    agent = PlanningAgent(_NoLLM())
    plan = _plan({1: [_visit("外滩", _BUND, 1), _visit("南京东路", _NANJING, 1)]})
    session = _session(plan)
    poi = {
        "name": "南翔馒头店",
        "city": "上海",
        "category": "food",
        "source_poi_id": "ct_上海_f1",
        "location": [121.4915, 31.2270],
        "suggested_duration_min": 60,
    }
    placement = place_food(
        agent, session, name="南翔馒头店", poi=poi, city="上海", item_id="v-food1"
    )
    assert placement is not None
    assert placement.kind == "food"
    assert placement.item.category == "food"
    assert placement.item.start_time is not None
    # 餐件不能在 09:00 当景点排——餐窗口径开席 ≥10:30
    assert placement.item.start_time.hour >= 10


def test_poi_kind_routes_food_and_hotel():
    from app.services.agent.wish_fast import _poi_kind

    assert _poi_kind({"category": "food"}) == "food"
    assert _poi_kind({"category": "hotel"}) == "hotel"
    assert _poi_kind({"category": "park"}) == "sight"
    assert _poi_kind({"category": "airport"}) == "other"


# --- 3. 快路径零 LLM -------------------------------------------------------


class _NoLLM:
    calls = 0

    async def chat(self, *args, **kwargs):  # pragma: no cover - 触发即失败
        _NoLLM.calls += 1
        raise AssertionError("fast wish path must not call the LLM")


class _StubAgent:
    """只实现快路径用到的那几个 agent 表面（其余一律不许碰）。"""

    def __init__(self, poi: dict | None) -> None:
        self._poi = poi
        self._llm = _NoLLM()
        self._item_seq = 0
        self._wish_bindings: dict[str, dict] = {}
        self.synced: list[list[str]] = []

    async def _poi_library_lookup(self, session, name, search_kw, city):
        if self._poi and city == "上海":
            return dict(self._poi)
        return None

    async def _lookup_poi(self, name, city):  # pragma: no cover - 不该走网络
        raise AssertionError("library hit must not hit the network")

    def alloc_item_id(self, plan=None, *, prefix="v"):
        self._item_seq += 1
        return f"{prefix}new{self._item_seq}"

    async def sync_wishes_to_trip_items(self, session, wishes, *, user_texts=None):
        self.synced.append(list(wishes))
        return [], []

    def _sync_wish_rows(self, session):
        return None

    def _sync_planned_rows(self, session):
        return None


def _session(plan: ItineraryPlan) -> PlanSession:
    session = PlanSession(
        session_id="s-fast",
        device_id="d-fast",
        cities=["上海"],
        days=2,
        state="ready",
    )
    session.plan = plan
    return session


def test_try_fast_wish_places_without_llm():
    plan = _plan(
        {
            1: [_visit("外滩", _BUND, 1, tier=2), _visit("南京东路", _NANJING, 1)],
            2: [_visit("迪士尼", _DISNEY, 2)],
        }
    )
    session = _session(plan)
    agent = _StubAgent(_poi())
    _NoLLM.calls = 0
    out = asyncio.run(try_fast_wish(agent, session, "我要去豫园"))
    assert out is not None
    new_session, reply, _change = out
    assert "豫园" in reply and "第1天" in reply
    assert _NoLLM.calls == 0
    assert any(i.name == "豫园" for d in new_session.plan.days for i in d.items)
    assert "豫园" in new_session.must_visits
    assert agent.synced == [["豫园"]]
    # 历史里留下回复（H5 直接渲染最后一条）
    assert new_session.history[-1].role == "assistant"


def test_try_fast_wish_already_planned_is_instant():
    plan = _plan(
        {
            1: [
                _visit("豫园", _YUYUAN, 1, tier=2),
                _visit("外滩", _BUND, 1, tier=2),
            ]
        }
    )
    day = plan.days[0]
    day.items[0].start_time = _time(9, 0)
    day.items[0].end_time = _time(10, 30)
    session = _session(plan)
    agent = _StubAgent(_poi())
    out = asyncio.run(try_fast_wish(agent, session, "我要去豫园"))
    assert out is not None
    _new_session, reply, _ = out
    assert "已经在第1天" in reply
    assert _NoLLM.calls == 0


def test_try_fast_wish_schedules_existing_untimed_item():
    # 已在册但没时刻（生成时被挤出窗口）：就地补位，不走 LLM
    plan = _plan(
        {
            1: [
                _visit("豫园", _YUYUAN, 1, tier=2),
                _visit("外滩", _BUND, 1, tier=2),
            ]
        }
    )
    session = _session(plan)
    agent = _StubAgent(None)
    _NoLLM.calls = 0
    out = asyncio.run(try_fast_wish(agent, session, "我要去豫园"))
    assert out is not None
    new_session, reply, _ = out
    assert "第1天" in reply and "已经在" not in reply
    assert _NoLLM.calls == 0
    placed = next(i for d in new_session.plan.days for i in d.items if i.name == "豫园")
    assert placed.start_time is not None


def test_try_fast_wish_passes_unknown_place_back():
    plan = _plan({1: [_visit("外滩", _BUND, 1, tier=2)]})
    session = _session(plan)
    agent = _StubAgent(None)
    assert asyncio.run(try_fast_wish(agent, session, "我要去豫园")) is None
    assert all(i.name != "豫园" for d in session.plan.days for i in d.items)


def test_place_wish_tiananmen_starts_at_flag_rise_time():
    """UAT 修复回归（2026-11-14）：快语心愿插天安门不经过 _plan_poi_hours
    （place_wish 纯计算路径）——兜底自身打标（_apply_flag_schedule 挂在
    _fallback_sequence_times 顶部）后走旗时锚，卡片开始时间 = 当日升旗
    时刻（种子 2026-11-14 → 6:58，可破 8:30 日始）。不落标则按 9:00
    头位排，正是 UAT「没拿到库内真值」的根因。"""
    plan = ItineraryPlan(
        itinerary_id="it-flag-wish",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    VisitItem(
                        item_id="v-gugong",
                        name="故宫博物院",
                        city="北京",
                        day=1,
                        duration_minutes=180,
                        location=GeoPoint(lon=116.397, lat=39.916),
                        category="sight",
                        tier=1,
                    )
                ],
            )
        ],
        start_date="2026-11-14",
    )
    poi = {
        "source_poi_id": "B000A8UIN8",
        "name": "天安门广场",
        "city": "北京",
        "category": "sight",
        "location": [116.397, 39.903],
        "suggested_duration_min": 60,
    }
    placement = place_wish(
        plan, name="天安门广场", poi=poi, city="北京", item_id="v-tam"
    )
    assert placement is not None
    assert placement.item.start_time == _time(6, 58)
