"""名录本体优先级（2026-11-22 用户令「兵马俑 PRIORITY 最高，再怎么删也不会
删它」）。

三条口径：
1. 让位/清场通道（hotfix_1117）不得把 site_rank ≤ 10 的本体卡当凑数填充撤掉；
2. 一日 4 件闸按名录秩淘汰（低秩先出局），不再是「谁后到谁倒霉」；
3. 让位必须闭环——腾出的窗口当场交给未排必去回座，回座不成把撤掉的件
   原样放回（D2 只剩华清宫、下午空 5 小时的事故形态）。
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.hotfix_1117 import (
    _is_filler,
    evict_fillers_when_must_unseated,
    restore_evicted_fillers,
)
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem


def _v(
    item_id: str,
    name: str,
    *,
    day: int = 1,
    start: time | None = None,
    end: time | None = None,
    dur: int = 120,
    rank: int | None = None,
    must: bool = False,
    city: str = "西安",
    cat: str = "attraction",
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=name,
        poi_id=item_id,
        category=cat,
        city=city,
        day=day,
        duration_minutes=dur,
        start_time=start,
        end_time=end,
        site_rank=rank,
        must=must,
    )


def _plan(*days: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-landmark", cities=["西安"], days=list(days)
    )


def test_landmark_is_not_a_filler():
    """UNESCO 本体（秩 0）与 curated 精选（秩 10）都不是「未请求填充」。"""
    bingmayong = _v("v-bing", "秦始皇帝陵博物院", rank=0)
    huaqing = _v("v-hq", "华清宫", rank=10)
    junk = _v("v-junk", "某小公园", rank=None)
    jianzhu = _v("v-wall", "城墙·碑林历史文化景区", rank=30)
    assert _is_filler(bingmayong) is False
    assert _is_filler(huaqing) is False
    assert _is_filler(junk) is True
    assert _is_filler(jianzhu) is True


def test_curated_experience_card_is_still_a_filler():
    """体验件不受保护：curated 茶馆（秩 10）照旧是填充，远郊日清场不能被卡。"""
    tea = _v("v-tea", "老舍茶馆", rank=10, cat="tea_experience")
    show = _v("v-show", "《秦俑情》", rank=10, cat="entertainment")
    assert _is_filler(tea) is True
    assert _is_filler(show) is True


def test_yield_takes_only_fillers_and_keeps_the_landmark():
    """必去未排上时，让位只动凑数件——兵马俑/华清宫留在当天。"""
    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("v-must", "《梦回大唐》", must=True, dur=120),  # 无时刻灰卡=触发让位
            _v("v-hq", "华清宫", start=time(9, 0), end=time(13, 0), dur=240, rank=10),
            _v("v-bing", "秦始皇帝陵博物院", start=time(14, 0), end=time(18, 0),
               dur=240, rank=0),
            _v("v-junk", "某小公园", start=time(18, 30), end=time(19, 30), dur=60),
        ],
    )
    plan = _plan(day1)
    evicted: list[tuple[int, int, object]] = []
    notes = evict_fillers_when_must_unseated(plan, must_names=[], evicted=evicted)

    names = [i.name for i in day1.items]
    assert "秦始皇帝陵博物院" in names
    assert "华清宫" in names
    assert "某小公园" not in names
    assert [(e[0], e[2].name) for e in evicted] == [(1, "某小公园")]
    assert len(notes) == 1


def test_restore_puts_the_evicted_card_back_in_place():
    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _v("v-must", "《梦回大唐》", must=True),
            _v("v-hq", "华清宫", start=time(9, 0), end=time(13, 0), dur=240, rank=10),
            _v("v-junk", "某小公园", start=time(18, 30), end=time(19, 30), dur=60),
            _v("v-bing", "秦始皇帝陵博物院", start=time(14, 0), end=time(18, 0),
               dur=240, rank=0),
        ],
    )
    plan = _plan(day1)
    evicted: list[tuple[int, int, object]] = []
    evict_fillers_when_must_unseated(plan, must_names=[], evicted=evicted)
    assert [i.name for i in day1.items] == [
        "《梦回大唐》",
        "华清宫",
        "秦始皇帝陵博物院",
    ]

    notes = restore_evicted_fillers(plan, evicted)
    # 原序号 2 → 放回华清宫之后、兵马俑之前
    assert [i.name for i in day1.items] == [
        "《梦回大唐》",
        "华清宫",
        "某小公园",
        "秦始皇帝陵博物院",
    ]
    assert len(notes) == 1
    # 幂等：再放一次不重复插卡
    assert restore_evicted_fillers(plan, evicted) == []
    assert len([i for i in day1.items if i.name == "某小公园"]) == 1


def test_cap_drops_the_lowest_rank_first():
    """一日 4 件闸按名录秩淘汰：兵马俑/华清宫永远不先出局。"""
    from app.services.agent.plan import PlanningAgent

    picked = [
        {"day": 1, "name": "秦始皇帝陵博物院", "category": "museum",
         "duration_minutes": 240, "site_rank": 0},
        {"day": 1, "name": "华清宫", "category": "attraction",
         "duration_minutes": 240, "site_rank": 10},
        {"day": 1, "name": "城墙·碑林历史文化景区", "category": "historic",
         "duration_minutes": 180, "site_rank": 30},
        {"day": 1, "name": "某小公园", "category": "park",
         "duration_minutes": 60, "site_rank": 40},
        {"day": 1, "name": "某寺", "category": "temple",
         "duration_minutes": 60, "site_rank": 40},
    ]
    kept, dropped = PlanningAgent._cap_sights_per_day(picked)
    assert [s["name"] for s in kept] == [
        "秦始皇帝陵博物院",
        "华清宫",
        "城墙·碑林历史文化景区",
        "某小公园",
    ]
    assert [d[0] for d in dropped] == ["第1天 某寺"]


def test_cap_still_respects_must_and_food_exemptions():
    from app.services.agent.plan import PlanningAgent

    picked = [
        {"day": 1, "name": f"杂点{i}", "category": "attraction",
         "duration_minutes": 60, "site_rank": 40}
        for i in range(5)
    ] + [
        {"day": 1, "name": "颐和园", "category": "park",
         "duration_minutes": 300, "site_rank": 0, "must": True},
        {"day": 1, "name": "某餐厅", "category": "food",
         "duration_minutes": 90, "site_rank": 40},
    ]
    kept, dropped = PlanningAgent._cap_sights_per_day(picked)
    names = [s["name"] for s in kept]
    assert "颐和园" in names and "某餐厅" in names
    assert names.count("颐和园") == 1
    # must 计件：4 席里 1 席被必去占，杂点只留 3 个
    assert len([n for n in names if n.startswith("杂点")]) == 3
    assert len(dropped) == 2


def test_heavy_day_trim_spares_the_landmark():
    """重日减负不拿名录本体开刀（凑数件照旧让位）。"""
    from app.services.agent.plan import PlanningAgent

    picked = [
        {"day": 1, "name": "颐和园", "category": "park",
         "duration_minutes": 300, "site_rank": 0, "must": True},
        {"day": 1, "name": "秦始皇帝陵博物院", "category": "museum",
         "duration_minutes": 240, "site_rank": 0},
        {"day": 1, "name": "某寺", "category": "temple",
         "duration_minutes": 60, "site_rank": 40},
    ]
    kept, dropped = PlanningAgent._trim_optional_sights_on_heavy_days(picked)
    names = [s["name"] for s in kept]
    assert "秦始皇帝陵博物院" in names
    assert "某寺" not in names
    assert [d[0] for d in dropped] == ["第1天 某寺"]


def test_closure_disclosure_suppresses_the_generic_unseated_line():
    """闭馆已单独披露的必去，不再补「当天排不下」（故宫周一闭馆案）。"""
    from app.api.plan import _audit_must_coverage
    from app.services.trip_orchestrator.session import PlanSession

    day1 = DayPlan(
        day=1,
        base_city="北京",
        items=[_v("v-gugong", "故宫博物院", must=True, rank=0, dur=240, city="北京")],
    )
    plan = _plan(day1)
    plan.cities = ["北京"]
    plan.assumptions = ["「故宫博物院」当天闭馆，本次未排时刻（可指定其他天）"]
    session = PlanSession(
        session_id="s-closure-dedupe",
        device_id="d-test",
        cities=["北京"],
        days=1,
        must_visits=["故宫博物院"],
        lang="zh",
        plan=plan,
    )
    _audit_must_coverage(session)

    assert [u.name for u in session.plan.unplaced] == ["故宫博物院"]
    assert not any(
        "暂未排上时刻" in a for a in session.plan.assumptions
    ), "闭馆原因已披露，不该再叠一条「当天排不下」"
    assert any("闭馆" in a for a in session.plan.assumptions)


def test_audit_gate_restores_fillers_when_the_must_cannot_be_seated():
    """让位闭环：回座不成 → 撤掉的件原样放回，天不再被掏空。"""
    from app.api.plan import _audit_must_coverage
    from app.services.trip_orchestrator.session import PlanSession

    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            # 600 分钟的必去：任何窗口都放不下 → 回座必然失败
            _v("v-show", "《梦回大唐》", must=True, dur=600),
            _v("v-hq", "华清宫", start=time(9, 0), end=time(13, 0), dur=240, rank=10),
            _v("v-bing", "秦始皇帝陵博物院", start=time(14, 0), end=time(18, 0),
               dur=240, rank=0),
            _v("v-junk", "某小公园", start=time(18, 30), end=time(19, 30), dur=60),
        ],
    )
    session = PlanSession(
        session_id="s-landmark-restore",
        device_id="d-test",
        cities=["西安"],
        days=1,
        must_visits=["《梦回大唐》"],
        lang="zh",
        plan=_plan(day1),
    )
    _audit_must_coverage(session)

    names = [i.name for i in session.plan.days[0].items]
    assert "秦始皇帝陵博物院" in names, "兵马俑不许被让位撤掉"
    assert "华清宫" in names
    assert "某小公园" in names, "回座失败必须把让位的件放回，不许空转"
    assert any("已放回原时段" in a for a in session.plan.assumptions)
