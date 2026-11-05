# -*- coding: utf-8 -*-
"""优先级尽早·初排偏好（2026-11-02 拍板链「兵马俑是 UNESCO 第一等级
应该尽早安排」→「全部优先级都要考虑」→「只是初排偏好，后面根据
具体情况可以调换」）。

①选点预占位——池内全部候选（演出除外）按完整优先级梯子 tier1→9
  预占最早有容量天（簇分日按最优成员排名会把高档王牌挤到行程尾部，
  兵马俑落第 5 天事故形态）；
②搁浅搬迁序——离城/到达侧搬迁按 tier 1→9 升序（全档），高档先挑
  余位；
③初排偏好非硬闸——LNS 评分改进时已定时 tier1 同样可后移（拆日重建
  仅保留 tier1 优先重插序）。
"""

from datetime import time

from app.services.agent.plan import (
    PlanningAgent,
    _priority_early_enabled,
    _reconcile_transfer_days,
)
from app.services.itinerary.models import (
    DayPlan,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)


def _sight(name, lon, lat, *, dur=120, tags=None, rain_ok=None, city="西安"):
    c = {
        "name": name,
        "city": city,
        "category": "sight",
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
    }
    if tags is not None:
        c["tags"] = tags
    if rain_ok is not None:
        c["rain_ok"] = rain_ok
    return c


# ---------- ① 选点预占位 ----------

_C1 = (108.94, 34.26)
_C2 = (108.78, 34.35)
_C3 = (109.02, 34.15)
_FAR = (109.28, 34.39)  # 远簇王牌（与市区簇 ~30km 拉开）


def _bmy_pool():
    # 三个 60 分钟 tier1 分守三个市区簇 + 240 分钟 tier1 远簇王牌：
    # 池序短时长优先=王牌殿后（pos3），簇日按最优成员排名=王牌簇 day4。
    return [
        _sight("甲馆", *_C1, dur=60, tags=["unesco"]),
        _sight("乙园", *_C2, dur=60, tags=["unesco"]),
        _sight("丙所", *_C3, dur=60, tags=["unesco"]),
        _sight("世遗王牌", *_FAR, dur=240, tags=["unesco"]),
    ]


def test_tier1_preclaim_beats_cluster_tail():
    items = PlanningAgent._deterministic_selection(_bmy_pool(), 4, {"西安": (1, 4)})
    day_of = {it["name"]: it["day"] for it in items}
    # 预占位：市区小点填满 day1（180/360）前，王牌先认领 day2——
    # 不再被簇排名推到行程最后一天。
    assert day_of["世遗王牌"] == 2


def test_preclaim_off_restores_cluster_tail(monkeypatch):
    monkeypatch.setenv("CHINATRIP_PRIORITY_EARLY", "off")
    assert not _priority_early_enabled()
    items = PlanningAgent._deterministic_selection(_bmy_pool(), 4, {"西安": (1, 4)})
    day_of = {it["name"]: it["day"] for it in items}
    # 旧行为（事故形态）：四个单例簇按最优成员排名，王牌簇 day4=最后一天。
    assert day_of["世遗王牌"] == 4


def test_preclaim_respects_rain_hard_gate():
    # 全窗有雨时露天 tier1 不硬塞雨日（与主环雨日硬闸同口径），
    # 交回填层/披露——预占位绝不单独破闸。
    cands = [
        _sight("露天王牌", *_FAR, dur=120, tags=["unesco"], rain_ok="no"),
        _sight("室内甲", *_C1, dur=90, tags=["unesco"], rain_ok="yes"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands,
        2,
        {"西安": (1, 2)},
        rain_days={"西安": {1, 2}},
        night_rain_days={"西安": {1, 2}},
    )
    names = [it["name"] for it in items]
    # 露天王牌全窗有雨 → 不由预占位塞进雨日（由后续雨通道处置）
    assert "室内甲" in names


# ---------- ② 搁浅搬迁序 ----------


def _stranded_plan(n1: str = "低档小点", n2: str = "世遗王牌") -> ItineraryPlan:
    d1 = [
        TransferItem(
            item_id="t1",
            day=1,
            seq=1,
            from_city="上海",
            to_city="西安",
            mode="train",
            start_time=time(15, 38),
            end_time=time(23, 59),
            duration_minutes=497,
        ),
        # 低档小点在列表序里排前——旧行为先到先得抢走 day2 余位
        VisitItem(item_id="a1", name=n1, city="西安", day=1, duration_minutes=90),
        VisitItem(item_id="a2", name=n2, city="西安", day=1, duration_minutes=90),
    ]
    d2 = [
        VisitItem(
            item_id="b1",
            name="已有甲",
            city="西安",
            day=2,
            start_time=time(9, 0),
            end_time=time(13, 20),
            duration_minutes=260,
        ),
        VisitItem(
            item_id="b2",
            name="已有乙",
            city="西安",
            day=2,
            start_time=time(14, 0),
            end_time=time(18, 20),
            duration_minutes=260,
        ),
        VisitItem(
            item_id="b3",
            name="午餐",
            city="西安",
            day=2,
            category="food",
            start_time=time(12, 0),
            end_time=time(13, 0),
            duration_minutes=60,
        ),
    ]
    return ItineraryPlan(
        itinerary_id="p",
        cities=["上海", "西安", "上海"],
        days=[
            DayPlan(day=1, base_city="上海", items=d1),
            DayPlan(day=2, base_city="西安", items=d2),
            DayPlan(day=3, base_city="西安", items=[]),
        ],
    )


def _day_of(plan: ItineraryPlan) -> dict[str, int]:
    return {
        v.name: v.day for d in plan.days for v in d.items if isinstance(v, VisitItem)
    }


def test_arrival_rescue_tier1_first():
    plan = _stranded_plan()
    _reconcile_transfer_days(plan, tier_by_name={"世遗王牌": 1, "低档小点": 2})
    days = _day_of(plan)
    # day2 余位只装得下一件：tier1 先挑 → 王牌 day2，低档点顺延 day3
    assert days["世遗王牌"] == 2
    assert days["低档小点"] == 3


def test_arrival_rescue_list_order_without_tiers():
    plan = _stranded_plan()
    _reconcile_transfer_days(plan)
    days = _day_of(plan)
    # 旧行为（事故形态）：列表序先到先得，低档点抢走 day2。
    assert days["低档小点"] == 2
    assert days["世遗王牌"] == 3


def test_arrival_rescue_full_ladder_beyond_tier1():
    # 完整梯子（2026-11-02 用户拍板「不止 tier1」）：tier2 也先于
    # 低档挑余位。
    plan = _stranded_plan(n1="低档点", n2="五甲点")
    _reconcile_transfer_days(plan, tier_by_name={"五甲点": 2, "低档点": 9})
    days = _day_of(plan)
    assert days["五甲点"] == 2
    assert days["低档点"] == 3


# ---------- ③ LNS 守卫 ----------


def _lns_plan() -> ItineraryPlan:
    anchor = VisitItem(
        item_id="v1",
        name="世遗王牌",
        city="西安",
        day=2,
        start_time=time(9, 0),
        end_time=time(12, 0),
        duration_minutes=180,
    )
    # 390 分钟巨点（11-05 结束闸下日容 ≤450：600min 永无解、让位机制
    # 失去意义；390 = 王牌占 day2 上午时午后空窗 12:00-16:30 装不下、
    # 王牌走后全天 09:00-15:00 恰可）：唯一「解法」是把定时王牌腾去
    # day3 上午给巨点让位。占日点 pinned（铁律 19）豁免结束闸——
    # unpinned 12:30-21:30 在 CP 里越闸不可行，resched 会拒绝挪王牌。
    u = VisitItem(
        item_id="v3", name="未排巨点", city="西安", day=2, duration_minutes=390
    )
    w = VisitItem(
        item_id="v4",
        name="占日点",
        city="西安",
        day=3,
        start_time=time(12, 30),
        end_time=time(21, 30),
        duration_minutes=540,
        pinned=True,
    )
    return ItineraryPlan(
        itinerary_id="p",
        cities=["西安"],
        days=[
            DayPlan(day=2, base_city="西安", items=[anchor, u]),
            DayPlan(day=3, base_city="西安", items=[w]),
        ],
    )


_LNS_CANDS = [
    {
        "name": "世遗王牌",
        "city": "西安",
        "category": "sight",
        "tags": ["unesco"],
        "location": {"lon": 109.28, "lat": 34.39},
        "suggested_duration_min": 180,
    }
]


def _run_lns(plan: ItineraryPlan):
    agent = object.__new__(PlanningAgent)
    # 占日点=必去（不可挪）：逼出「唯一解=定时王牌让位去 day3 上午」
    # 的差异场景——否则 LNS 用巨点↔占日点对调就能解，不碰王牌。
    picked = [{"name": "占日点", "must": True}]
    return PlanningAgent._global_resched(agent, plan, picked, _LNS_CANDS)


def test_preclaim_full_ladder_spreads_by_cap():
    # 全档预占位（2026-11-02 用户拍板「全部优先级都要考虑」）：同坐标
    # 消腿噪声，4/日闸下高档先满 day1、次档顺延 day2。
    cands = [
        _sight("甲馆", *_C1, dur=90, tags=["unesco"]),
        _sight("乙5a", *_C1, dur=90, tags=["5a"]),
        _sight("丙5a", *_C1, dur=90, tags=["5a"]),
        _sight("丁lp", *_C1, dur=90, tags=["lp"]),
        _sight("戊lp", *_C1, dur=90, tags=["lp"]),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"西安": (1, 2)})
    day_of = {it["name"]: it["day"] for it in items}
    assert day_of["甲馆"] == 1
    assert day_of["乙5a"] == 1 and day_of["丙5a"] == 1
    assert day_of["丁lp"] == 1  # 池序第 4 件，day1 恰好满 4 点
    assert day_of["戊lp"] == 2  # 次档顺延，不越档抢更早的天


def test_lns_may_relocate_timed_tier1_when_it_unlocks():
    # 2026-11-02 用户更正：优先级只是初排偏好——LNS 评分改进时
    # 已定时 tier1 也可后移（巨点因此解开未排卡）。
    plan = _lns_plan()
    moves = _run_lns(plan)
    days = _day_of(plan)
    assert days["世遗王牌"] == 3
    giant = next(
        v
        for d in plan.days
        for v in d.items
        if isinstance(v, VisitItem) and v.name == "未排巨点"
    )
    assert giant.start_time is not None
    assert any("世遗王牌" in m and "第3天" in m for m in moves[0])
