"""引擎常识约束评测集（DESIGN §8.1.5，升 P0 硬闸门 2026-10-24 §14.4）。

对照 TravelPlanner（ICML'24）的常识约束体系——GPT-4 裸排通过率仅
0.6%、最常挂的恰是这类约束：同一餐厅一天不重复、每天景点数上限、
日步行预算（铁律 6）。任何引擎改动必须保持本文件全绿；改动导致
约束回归 = 改动不可合入。
"""

from datetime import time as dtime

from app.services.agent.plan import PlanningAgent
from app.services.itinerary import VisitItem
from app.services.itinerary.models import DayPlan, ItineraryPlan
from app.services.poi_details import PoiDetailStore
from tests.test_plan_agent import (  # noqa: F401  (fixtures)
    AMAP_POIS,
    ScriptedLLM,
    StubAmap,
    all_visits,
    run,
    v0_reply,
)


def _agent(items, amap_pois=AMAP_POIS):
    return PlanningAgent(
        ScriptedLLM([v0_reply(items)]), amap_client=StubAmap(amap_pois)
    )


def _start(agent, *, days=1, city="上海"):
    return run(
        agent.start(device_id="eval", cities=[city], days=days, preferences="随便")
    )


def test_eval_no_duplicate_site_in_same_day():
    """同一点一天只出现一次（选点/去重层保证）。"""
    items = [
        {"name": "外滩", "city": "上海", "day": 1, "duration_minutes": 90},
        {"name": "外滩", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    session = _start(_agent(items))
    names = [v.name for v in all_visits(session) if v.name == "外滩"]
    assert len(names) == 1


def test_eval_day_sight_count_capped_at_four():
    """每天非 food 游览点 ≤4（LLM 过量输出被裁并记假设）。"""
    items = [
        {"name": n, "city": "上海", "day": 1, "duration_minutes": 60}
        for n in ["外滩", "豫园", "南京路步行街", "田子坊", "武康路", "静安寺"]
    ]
    session = _start(_agent(items))
    day1 = [v for v in all_visits(session) if v.day == 1 and v.category != "food"]
    assert len(day1) <= 4
    assert any("每日最多保留 4 个景点" in a for a in session.assumptions)


def test_eval_daily_walk_budget_violation_flagged():
    """铁律 6：日步行直线合计超 15km×系数 → validate_plan 必须报错级违规。"""
    from app.services.itinerary import GeoPoint, validate_plan
    from app.services.itinerary.rules import haversine_km

    far = [
        VisitItem(
            item_id=f"v{i}",
            name=f"远点{i}",
            city="上海",
            location=GeoPoint(lon=121.0 + i * 0.5, lat=31.2),  # ~46km 步距
            day=1,
        )
        for i in range(3)
    ]
    plan = ItineraryPlan(
        itinerary_id="eval",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=far)],
    )
    # 守恒断言：这组坐标真的超预算（否则本用例失效）
    total = sum(haversine_km(a.location, b.location) for a, b in zip(far, far[1:]))
    assert total > 15.0
    report = validate_plan(plan, poi_hours=[])
    # 铁律 6 为 warning 级（软信号——过载日提示用户，不硬拦交付）
    assert any(v.rule_id == 6 for v in report.violations), "95km/日必须触发铁律 6"


def test_eval_no_time_overlap_in_solved_v0():
    """铁律 1：v0 解出的同日游览点时间互不重叠。"""
    items = [
        {"name": "外滩", "city": "上海", "day": 1, "duration_minutes": 120},
        {"name": "豫园", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    session = _start(_agent(items))
    timed = [
        (v.start_time, v.end_time)
        for v in all_visits(session)
        if v.day == 1 and v.start_time and v.category != "food"
    ]
    timed.sort()
    for (s1, e1), (s2, _e2) in zip(timed, timed[1:]):
        assert e1 <= s2, f"重叠：{e1} > {s2}"


def test_eval_placeholder_free_when_stocked():
    """库存充足的城市候选不得落占位假 POI（8.1.1 库优先回归）。

    占位 POI 名 = 城市+PLACEHOLDER_POI_LABELS（上海博物馆/上海老街/
    上海公园/上海地标）；库存 12 ≥ 阈值时占位路径不应触发。
    """
    agent = PlanningAgent(
        ScriptedLLM(
            [
                v0_reply(
                    [
                        {
                            "name": "外滩",
                            "city": "上海",
                            "day": 1,
                            "duration_minutes": 90,
                        }
                    ]
                )
            ]
        ),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=_StockedStore(),
    )
    session = run(
        agent.start(device_id="eval", cities=["上海"], days=1, preferences="随便")
    )
    names = [v.name for v in all_visits(session)]
    assert names, "v0 must contain visits"
    placeholders = {"上海博物馆", "上海老街", "上海公园", "上海地标"}
    assert not any(n in placeholders for n in names)
    assert not any("POI 候选为占位" in a for a in session.assumptions)


class _StockedStore(PoiDetailStore):
    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return [
            {
                "source_poi_id": f"E{i:03d}",
                "name": f"评测景点{i}",
                "city": "上海",
                "category": "attraction",
                "rating": 4.5,
                "rating_count": 500,
                "tags": [],
                "best_visit_time": "any",
                "suggested_duration_min": None,
                "indoor": None,
                "rain_ok": None,
                "review_tags": [],
                "intro": None,
                "location": (121.45 + i * 0.01, 31.23),
            }
            for i in range(12)
        ]


# --- 扩样（2026-10-25 二轮）：窗/餐/链路级端到端约束 --------------------------


def _stocked(**overrides):
    """单候选库存店：name 默认「评测景点0」，kwargs 覆盖候选字段。"""
    row = {
        "source_poi_id": "E000",
        "name": "评测景点0",
        "city": "上海",
        "category": "attraction",
        "rating": 4.5,
        "rating_count": 500,
        "tags": [],
        "best_visit_time": "any",
        "suggested_duration_min": None,
        "indoor": None,
        "rain_ok": None,
        "review_tags": [],
        "intro": None,
        "location": (121.45, 31.23),
    }
    row.update(overrides)
    return row


class _OneStore(PoiDetailStore):
    def __init__(self, *rows):
        super().__init__()
        self._rows = list(rows)

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return self._rows


def test_eval_restaurant_rides_dinner_window():
    """铁律 20：v0 自动插入的晚餐必须落在晚餐窗（17:30-19:30）内。"""
    from app.services.restaurants import MEAL_WINDOWS

    items = [
        {"name": "外滩", "city": "上海", "day": 1, "duration_minutes": 90},
        {"name": "豫园", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    session = _start(_agent(items))
    foods = [v for v in all_visits(session) if v.category == "food"]
    assert len(foods) == 1
    lo, hi = MEAL_WINDOWS["dinner"]
    assert foods[0].start_time and lo <= foods[0].start_time < hi


def test_eval_best_visit_time_window_honored_end_to_end():
    """8.2.1 端到端：evening 候选解出后开始时间必须 ≥17:00。"""
    store = _OneStore(_stocked(best_visit_time="evening"))
    items = [
        {"name": "评测景点0", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=store,
    )
    session = _start(agent)
    v = next(v for v in all_visits(session) if v.name == "评测景点0")
    assert v.start_time is not None
    assert v.start_time.hour >= 17, f"evening 点被排到 {v.start_time}"


def test_eval_multi_window_lunch_gap_never_scheduled():
    """G3 端到端：午休闭馆分段「09:00-12:00,13:30-17:00」——
    解出的到访时段不得与闭馆 gap (12:00,13:30) 相交。"""
    store = _OneStore(_stocked(opening_hours="09:00-12:00,13:30-17:00"))
    items = [
        {"name": "评测景点0", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=store,
    )
    session = _start(agent)
    v = next(v for v in all_visits(session) if v.name == "评测景点0")
    assert v.start_time and v.end_time, "分段开窗候选必须解出时间"
    assert not (v.start_time < dtime(13, 30) and v.end_time > dtime(12, 0)), (
        f"到访 {v.start_time}-{v.end_time} 撞上午休闭馆"
    )


def test_eval_time_chain_end_matches_duration():
    """时链一致性：解出的每条 visit end-start ≥ 声明时长（不缩水）。"""
    items = [
        {"name": "外滩", "city": "上海", "day": 1, "duration_minutes": 120},
        {"name": "豫园", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    session = _start(_agent(items))
    for v in all_visits(session):
        if v.start_time and v.end_time and v.duration_minutes:
            span = (v.end_time.hour * 60 + v.end_time.minute) - (
                v.start_time.hour * 60 + v.start_time.minute
            )
            assert span >= v.duration_minutes, (
                f"{v.name} 时长被压缩 {span}<{v.duration_minutes}"
            )


def test_eval_reservation_hint_does_not_distort_schedule():
    """G1 交互：预约制候选照常参与求解（时间齐全、无重叠），
    hint 只是展示层——不因「需预约」被 solver 排斥或悬空。"""
    store = _OneStore(
        _stocked(reservation_required=True, reservation_advance_days=7),
        _stocked(name="评测景点1", source_poi_id="E001", location=(121.46, 31.24)),
    )
    items = [
        {"name": "评测景点0", "city": "上海", "day": 1, "duration_minutes": 90},
        {"name": "评测景点1", "city": "上海", "day": 1, "duration_minutes": 90},
    ]
    agent = PlanningAgent(
        ScriptedLLM([v0_reply(items)]),
        amap_client=StubAmap(AMAP_POIS),
        poi_details=store,
    )
    session = _start(agent)
    visits = [v for v in all_visits(session) if v.category != "food"]
    hinted = [v for v in visits if v.reservation_hint]
    assert hinted and "7" in hinted[0].reservation_hint
    timed = sorted((v.start_time, v.end_time) for v in visits if v.start_time)
    assert timed, "预约制候选不得导致时间悬空"
    for (s1, e1), (s2, _e2) in zip(timed, timed[1:]):
        assert e1 <= s2
