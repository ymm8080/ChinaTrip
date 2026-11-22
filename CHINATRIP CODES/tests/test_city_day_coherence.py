# -*- coding: utf-8 -*-
"""城市日一致性（2026-11-22 用户实录：上海→西安→北京 7 天）。

用户原话：
- 「第一天是上海到西安，第二天安排北京行程。完全错误。应该安排西安行程」
- 「第五条北京行程里还有一个上海外滩景点」

根因（本文件的回归锚）：
1. `_assign_must_family_days` 无宿主日时回落 anchor 天；`score` 用
   `_day_hosts_city` 读「已在册条目城市」→ 混日卡自我认证；
2. `_separate_remote_must_days` 只按「别的必去最少」挑宿主日，完全没有
   城市闸（慕田峪 = 北京远郊必去 → 被搬进西安第 2 天）；
3. `fill_leftover_gaps` 补点池只靠几何亲和闸，转场日 day_pts 为空时闸
   形同虚设（外滩 = 上海 → 被补进西安→北京的第 5 天）；
4. 终装三轴校核的城市轴只比「转场前后钟点」，没有转场的天永远合规；
   `validate_plan` 只问「城市在不在行程城市表里」（外滩在上海=表内 → 零告警）。

修法：骨架口径（基准城 + 当天城际腿两端）+ 交付边界总闸
`_enforce_city_coherence`。
"""

from datetime import time as _t

from app.services.agent.plan import (
    _day_city_capacity,
    _day_city_skeleton,
    _enforce_city_coherence,
    _separate_remote_must_days,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.rules import validate_plan

SH = (121.4737, 31.2304)
XA = (108.9402, 34.3416)
BJ = (116.4074, 39.9042)


def _visit(item_id, name, *, city, day, dur=120, xy=None, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city=city,
        day=day,
        duration_minutes=dur,
        category="sight",
        location=None if xy is None else GeoPoint(lon=xy[0], lat=xy[1]),
    )
    base.update(kw)
    return VisitItem(**base)


def _transfer(day, frm, to, *, start="09:00", end="12:00"):
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    return TransferItem(
        item_id=f"t{day}",
        day=day,
        seq=1,
        from_city=frm,
        to_city=to,
        mode="flight",
        start_time=_t(sh, sm),
        end_time=_t(eh, em),
        duration_minutes=(eh * 60 + em) - (sh * 60 + sm),
    )


def _route_plan() -> ItineraryPlan:
    """上海(出发)→西安 4 天→北京 3 天，与用户实测会话同形。"""
    d1 = DayPlan(day=1, base_city="上海", items=[_transfer(1, "上海", "西安")])
    d2 = DayPlan(day=2, base_city="西安", items=[])
    d3 = DayPlan(day=3, base_city="西安", items=[])
    d4 = DayPlan(day=4, base_city="西安", items=[])
    d5 = DayPlan(day=5, base_city="西安", items=[_transfer(5, "西安", "北京")])
    d6 = DayPlan(day=6, base_city="北京", items=[])
    d7 = DayPlan(day=7, base_city="北京", items=[])
    return ItineraryPlan(
        itinerary_id="it-citymix",
        cities=["上海", "西安", "北京"],
        days=[d1, d2, d3, d4, d5, d6, d7],
    )


def _find(plan, name):
    for d in plan.days:
        for i in d.items:
            if isinstance(i, VisitItem) and i.name == name:
                return d.day, i
    return None, None


def test_day_city_skeleton_reads_route_not_cards():
    plan = _route_plan()
    # 出发日骨架两端（卡片自己写什么都不影响判定）
    plan.days[0].items.append(_visit("v-x", "永兴坊", city="西安", day=1, xy=XA))
    assert _day_city_skeleton(plan.days[0]) == {"上海", "西安"}
    assert _day_city_skeleton(plan.days[1]) == {"西安"}
    assert _day_city_skeleton(plan.days[5]) == {"北京"}


def test_capacity_rules_out_departure_only_city():
    """「很清晰的离开城市、到达城市」：出发城当天没有可玩时间。

    上海 D1 09:00 起飞 → 上海容量 0（没有"没有宿主日"这种模糊态，就是排不进）；
    同一张盘面里西安落地后可玩 420 分钟、D5 北京落地后可玩 420 分钟。
    补点池按容量过滤 → 上海外滩根本不会被捞回来。
    """
    plan = _route_plan()
    assert _day_city_capacity(plan.days[0], "上海") == 0
    assert _day_city_capacity(plan.days[0], "西安") == 420
    assert _day_city_capacity(plan.days[4], "西安") == 0
    assert _day_city_capacity(plan.days[4], "北京") == 420


def test_foreign_city_card_moves_to_its_own_day():
    plan = _route_plan()
    # 第 2 天（西安）混进北京景点——用户实录第一条
    plan.days[1].items.append(
        _visit("v-mt", "慕田峪长城", city="北京", day=2, dur=240, xy=BJ)
    )
    notes = _enforce_city_coherence(plan)
    day_no, item = _find(plan, "慕田峪长城")
    assert day_no in (6, 7), f"北京景点必须落在北京的天，实际第{day_no}天"
    assert item is not None and notes


def test_wrong_city_card_without_host_day_leaves_the_plan():
    plan = _route_plan()
    # 第 5 天（西安→北京）混进上海外滩——用户实录第二条
    plan.days[4].items.append(
        _visit("extras-5-外滩", "外滩", city="上海", day=5, dur=120, xy=SH)
    )
    notes = _enforce_city_coherence(plan)
    day_no, _ = _find(plan, "外滩")
    assert day_no is None, "本行程没有上海停留日，外滩不许留在任何一天"
    assert any("外滩" in str(n) for n in notes)
    assert any(u.name == "外滩" for u in plan.unplaced), "移出必须进想去（可挪不可删）"


def test_remote_must_never_moves_into_another_citys_day():
    """慕田峪（北京远郊必去）不得被「别的必去最少」搬进西安第 2 天。"""
    plan = _route_plan()
    plan.days[5].items.append(
        _visit(
            "v-mt",
            "慕田峪长城",
            city="北京",
            day=6,
            dur=240,
            xy=BJ,
            must=True,
            remote=True,
        )
    )
    # 北京另两天都有城心必去（慕田峪「别的必去最少」的天其实在西安）
    plan.days[5].items.append(
        _visit("v-yhy", "颐和园", city="北京", day=6, dur=180, xy=BJ, must=True)
    )
    plan.days[6].items.append(
        _visit("v-gug", "故宫博物院", city="北京", day=7, dur=240, xy=BJ, must=True)
    )
    _separate_remote_must_days(plan)
    day_no, _ = _find(plan, "慕田峪长城")
    assert day_no in (6, 7), f"远郊必去只能占自己那座城的天，实际第{day_no}天"


def test_validate_plan_flags_city_day_mismatch():
    plan = _route_plan()
    plan.days[1].items.append(_visit("v-tam", "天安门广场", city="北京", day=2, xy=BJ))
    report = validate_plan(plan, poi_hours=[])
    assert any(
        v.rule_id == 3 and "天安门广场" in str(v.message) for v in report.violations
    ), "城市混日必须有告警（旧校验只问城市在不在行程表里，外滩/天安门全静默）"
