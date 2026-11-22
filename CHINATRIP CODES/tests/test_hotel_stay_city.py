# -*- coding: utf-8 -*-
"""酒店卡城市口径（2026-11-22 用户实录 FIX）。

用户原话：
- 「第四天从西安到北京，酒店应该住北京，测试显示西安。」
- 「第五天早上也是从北京酒店出发，测试结果是从西安酒店出发。」

实测会话（h5_state.db / c61f24db，上海→西安 4 天→北京 2 天）的盘面：
D4 = 西安→北京 城际腿日，到达城北京的卡只有入住/晚饭；夜卡是引擎缝在排程期
物化的，城市取「当日多数城」，当天到达城的卡还没落时退化成城市序索引 = 出发城
西安 → D4 夜卡写西安；D5 晨卡由 attach_hotel_mornings 从夜卡继承 → 也写西安。

本文件的回归锚：
1. `itinerary.stay_city` 口径 —— 晚宿城按**时链**取末个落脚点，末段城际腿
   到达城优先；离程腿（回家/离开行程城）不算落脚；
2. `attach_hotel_nights` 初插夜卡吃同一口径（列表序≠时链）；
3. `sync_stay_cities` 交付边界保险闸 —— 引擎物化的错城夜卡被拨正，次日晨卡
   跟着正；已验证真实酒店不动；幂等。
"""

from datetime import time

from app.services.agent.hotel_stays import (
    attach_hotel_mornings,
    attach_hotel_nights,
    sync_stay_cities,
)
from app.services.itinerary.models import DayPlan, TransferItem, VisitItem
from app.services.itinerary.stay_city import stay_city


def _visit(item_id, name, city, day, *, start=None, end=None, dur=120, **kw):
    return VisitItem(
        item_id=item_id,
        name=name,
        city=city,
        day=day,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        category=kw.pop("category", "sight"),
        **kw,
    )


def _xfer(item_id, day, frm, to, *, start=(9, 0), end=(12, 0), mode="train"):
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=1,
        from_city=frm,
        to_city=to,
        mode=mode,
        start_time=time(*start),
        end_time=time(*end),
        duration_minutes=(end[0] * 60 + end[1]) - (start[0] * 60 + start[1]),
    )


def _night(dp):
    return next((i for i in dp.items if i.item_id.startswith("hotel-night")), None)


def _morning(dp):
    return next((i for i in dp.items if i.item_id.startswith("hotel-morning")), None)


# --------------------------------------------------------------- 口径本体


def test_stay_city_transfer_only_day_is_arrival_city():
    """跨城日只有一张城际腿（到达城还没排卡）：晚宿城只能是到达城。"""
    d4 = DayPlan(day=4, base_city="西安", items=[_xfer("t4", 4, "西安", "北京")])
    assert stay_city(d4.items, d4.base_city) == "北京"


def test_stay_city_return_leg_is_not_a_stop():
    """回家腿（到达城不是任何更晚日子的宿城）不算落脚：仍住北京。"""
    d7 = DayPlan(
        day=7,
        base_city="北京",
        items=[
            _visit(
                "v1",
                "颐和园",
                "北京",
                7,
                start=time(11, 30),
                end=time(16, 30),
                dur=300,
            ),
            _xfer("t7", 7, "北京", "返程地", start=(21, 30), end=(23, 30)),
        ],
    )
    assert stay_city(d7.items, d7.base_city, stay_cities={"北京"}) == "北京"


def test_stay_city_prefers_latest_stop_over_list_order():
    """列表顺序是排程相位的副作用：晚宿城只看时刻最晚的落脚点。"""
    d4 = DayPlan(
        day=4,
        base_city="西安",
        items=[
            _xfer("t4", 4, "西安", "北京"),
            _visit(
                "v-bj",
                "天坛",
                "北京",
                4,
                start=time(14, 30),
                end=time(17, 0),
            ),
            # 出发城的卡排在列表最后，但时刻更早 —— 不许它决定夜宿城
            _visit(
                "v-xa",
                "西安城墙",
                "西安",
                4,
                start=time(8, 0),
                end=time(9, 0),
            ),
        ],
    )
    assert stay_city(d4.items, d4.base_city) == "北京"


# ------------------------------------------------------- 初插夜卡（legacy）


def test_attach_night_on_transfer_day_lands_arrival_city():
    """D4 西安→北京：夜卡城=北京（不是出发城西安）。"""
    d1 = DayPlan(day=1, base_city="西安", items=[])
    d4 = DayPlan(
        day=4,
        base_city="西安",
        items=[
            _xfer("t4", 4, "西安", "北京"),
            _visit("v-bj", "天坛", "北京", 4, start=time(14, 30), end=time(17, 0)),
        ],
    )
    d5 = DayPlan(day=5, base_city="北京", items=[])
    attach_hotel_nights([d1, d4, d5])
    assert _night(d4).city == "北京"


def test_attach_night_transfer_only_day_lands_arrival_city():
    """到达城一张观光卡都没排：夜卡城仍是到达城（旧实现退成醒来城）。"""
    d5 = DayPlan(day=5, base_city="北京", items=[])
    d4 = DayPlan(day=4, base_city="西安", items=[_xfer("t4", 4, "西安", "北京")])
    attach_hotel_nights([d4, d5])
    card = _night(d4)
    assert card is not None and card.city == "北京"


# ------------------------------------------------- 交付边界保险闸（引擎缝）


def _engine_style_plan() -> list[DayPlan]:
    """引擎物化后的错盘面：D4 夜卡写西安，D5 晨卡继承西安。"""
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            VisitItem(
                item_id="hotel-morning-d3",
                name="🏨 从酒店出发（今日起点）",
                city="西安",
                day=3,
                start_time=time(8, 30),
                end_time=time(9, 0),
                duration_minutes=30,
                category="hotel",
            ),
            _visit("v3", "华清宫", "西安", 3, start=time(9, 0), end=time(13, 0)),
            VisitItem(
                item_id="hotel-night-d3",
                name="🏨 回酒店·夜间休息",
                city="西安",
                day=3,
                start_time=time(21, 0),
                end_time=time(22, 0),
                duration_minutes=60,
                category="hotel",
            ),
        ],
    )
    d4 = DayPlan(
        day=4,
        base_city="西安",
        items=[
            VisitItem(
                item_id="hotel-morning-d4",
                name="🏨 从酒店出发（今日起点）",
                city="西安",
                day=4,
                start_time=time(6, 0),
                end_time=time(6, 30),
                duration_minutes=30,
                category="hotel",
            ),
            _xfer("t4", 4, "西安", "北京"),
            VisitItem(
                item_id="hotel-checkin-d4",
                name="🏨 酒店入住（放行李·休整）",
                city="北京",
                day=4,
                start_time=time(13, 30),
                end_time=time(14, 30),
                duration_minutes=60,
                category="hotel",
            ),
            _visit(
                "food-dinner-ph-d4",
                "晚饭（自由安排）",
                "北京",
                4,
                start=time(19, 0),
                end=time(20, 30),
                category="food",
            ),
            # 错城夜卡：引擎按「当日多数城」落的出发城
            VisitItem(
                item_id="hotel-night-d4",
                name="🏨 回酒店·夜间休息",
                city="西安",
                day=4,
                start_time=time(21, 0),
                end_time=time(22, 0),
                duration_minutes=60,
                category="hotel",
            ),
        ],
    )
    d5 = DayPlan(
        day=5,
        base_city="北京",
        items=[
            VisitItem(
                item_id="hotel-morning-d5",
                name="🏨 从酒店出发（今日起点）",
                city="西安",
                day=5,
                start_time=time(5, 15),
                end_time=time(5, 45),
                duration_minutes=30,
                category="hotel",
            ),
            _visit("v5", "慕田峪长城", "北京", 5, start=time(10, 8), end=time(14, 8)),
        ],
    )
    return [d3, d4, d5]


def test_sync_stay_cities_fixes_engine_night_and_next_morning():
    days = _engine_style_plan()
    assert _night(days[1]).city == "西安"  # 修复前
    assert sync_stay_cities(days) == 2
    assert _night(days[1]).city == "北京"  # 第四天住北京
    assert _morning(days[2]).city == "北京"  # 第五天从北京酒店出发


def test_sync_stay_cities_keeps_verified_hotel_and_is_idempotent():
    days = _engine_style_plan()
    night = _night(days[1])
    # 用户手输验证过的酒店（有地址/坐标）：系统不许改城，次日晨卡跟着这张卡走
    night.address = "西安市碑林区某路 1 号"
    assert sync_stay_cities(days) == 0
    assert night.city == "西安"
    assert _morning(days[2]).city == "西安"
    assert sync_stay_cities(days) == 0


def test_sync_stay_cities_leaves_clean_plan_untouched():
    d1 = DayPlan(day=1, base_city="西安", items=[])
    d2 = DayPlan(day=2, base_city="西安", items=[])
    attach_hotel_nights([d1, d2])
    attach_hotel_mornings([d1, d2])
    assert sync_stay_cities([d1, d2]) == 0
    assert _night(d2).city == "西安"
    assert _morning(d2).city == "西安"


# ------------------------------------------------------- 引擎缝（物化）


def test_engine_night_card_on_city_switch_day_is_arrival_city():
    """图引擎物化的夜卡：跨城日不许按「当日多数城」落成出发城。

    实测盘面（c61f24db D4）：到达城的卡还没排进来，多数城仍是出发城 →
    旧实现夜卡写西安。这里用「出发城两张卡 + 到达城一张卡、到达城的卡时刻最
    晚」的到达日锁死口径。
    """
    from app.services.trip_solver.assembly import materialize_plan
    from app.services.trip_solver.types import (
        CandidateItem,
        FactSnapshot,
        RequestedItem,
        Solution,
        SolutionItem,
        TripRequest,
    )

    def _cand(cid, name, city, lon, lat):
        return CandidateItem(
            cid=cid,
            name=name,
            poi_id=cid,
            kind="requested",
            rid=cid,
            category="historic",
            opening_hours="08:30-17:30",
            suggested_duration_min=90,
            lon=lon,
            lat=lat,
            remote=False,
            city=city,
        )

    snap = FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=2,
            cities=("北京", "西安"),
            musts=tuple(
                RequestedItem(rid=c, name=n, poi_id=c)
                for c, n in (("c1", "故宫"), ("c2", "天坛"), ("c3", "颐和园"))
            ),
        ),
        candidates=(
            _cand("c1", "故宫", "北京", 116.40, 39.92),
            _cand("c2", "天坛", "北京", 116.41, 39.88),
            _cand("c3", "颐和园", "北京", 116.27, 39.99),
            _cand("c4", "兵马俑", "西安", 109.28, 34.39),
        ),
        source="synthetic",
    )
    solution = Solution(
        status="FEASIBLE",
        items=[
            SolutionItem(cid="c1", day=1, start_min=540, end_min=660),
            # 到达日（D2，西安）：出发城两张卡 + 到达城一张卡（时刻最晚）
            SolutionItem(cid="c2", day=2, start_min=660, end_min=750),
            SolutionItem(cid="c3", day=2, start_min=780, end_min=870),
            SolutionItem(cid="c4", day=2, start_min=900, end_min=1020),
        ],
        hotel_anchors=[{"slot": "night", "day": 2, "start_min": 1260, "end_min": 1320}],
    )
    plan = materialize_plan(solution, snap)
    d2 = next(dp for dp in plan.days if dp.day == 2)
    night = _night(d2)
    assert night is not None
    # 当晚睡西安（兵马俑那张卡所在城），不是出发城北京
    assert night.city == "西安"
