"""备选 chip 拖入时间轴（2026-11-14 拍板「备选要像其它条目一样可拖」）。

端点 POST /api/v1/plan/{sid}/items/{item_id}/insert-alt：把条目右侧的备选
（或「想去」chip）拖到某天两件之间即在该处插入一张新卡（主点保留）；当天
排不下时按档号/距离让位，撤下谁写进回复与假设标注。
"""

import asyncio
import os
from datetime import time as dtime

import pytest
from test_plan_api import (  # noqa: E402  （pytest 把 tests/ 加进 sys.path）
    DEVICE_HEADERS,
    V0_JSON,
    StubAdapter,
    _day_visits,
    _visit,
    client_for,
    start,
)

from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.itinerary import DayPlan, ItineraryPlan, VisitItem


class StubAltStore:
    """candidate_by_name 桩：名字→候选，未命中 None（其余库读给空实现）。"""

    def __init__(self, mapping: dict | None = None) -> None:
        self.mapping = mapping or {}
        self.calls: list = []

    def candidate_by_name(self, city, name):
        self.calls.append((city, name))
        return self.mapping.get(name)

    def db_degraded(self):
        return False

    def get(self, source_poi_id):
        return None

    def upsert(self, *a, **k):
        return None

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return []

    def search_keyword(self, city, tokens, *, limit=5):
        return []

    def get_by_name(self, city, name):
        return None


LINGYIN = {
    "source_poi_id": "ct_杭州_9",
    "name": "灵隐寺",
    "city": "杭州市",
    "category": "attraction",
    "address": "法云弄1号",
    "opening_hours": "07:00-23:00",
    "name_en": "Lingyin Temple",
    "address_en": None,
    "intro_en": None,
    "opening_hours_en": None,
    "best_visit_time": None,
    "booking_url": None,
    "rain_ok": "yes",
    "rating": 4.7,
    "tags": ["4a"],
    "suggested_duration_min": 75,
    "reservation_required": None,
    "reservation_advance_days": None,
    "location": (120.0972, 30.2414),
    "source": "4a",
}


@pytest.fixture(autouse=True)
def _llm_select_mode():
    """与 test_plan_api 同口径：本文件用桩 v0 JSON 起行程。"""
    os.environ["PLAN_SELECT_MODE"] = "llm"
    yield
    os.environ.pop("PLAN_SELECT_MODE", None)


def test_insert_alt_lands_after_anchor_and_keeps_host():
    store = StubAltStore({"灵隐寺": LINGYIN})
    agent = PlanningAgent(StubAdapter([V0_JSON]), poi_details=store)
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    host = _visit(body, "雷峰塔")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{host}/insert-alt",
        json={"name": "灵隐寺", "day": 2, "after_item_id": host},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [v["item_id"] for v in _day_visits(data, 2)]
    alt = _visit(data, "灵隐寺")
    assert alt["day"] == 2
    # 插在落点之后（不是换点：宿主雷峰塔还在）
    assert ids.index(alt["item_id"]) == ids.index(host) + 1
    assert _visit(data, "雷峰塔")["item_id"] == host
    assert store.calls == [("杭州", "灵隐寺")]  # 按宿主所在城收窄
    slots = [(v["start_time"], v["end_time"]) for v in _day_visits(data, 2)]
    assert all(s[0] and s[1] for s in slots)  # 当天时链完整
    assert alt["poi_id"] == "ct_杭州_9" and alt["duration_minutes"] == 75


def test_insert_alt_duplicate_422():
    store = StubAltStore({"西湖": {**LINGYIN, "name": "西湖", "source_poi_id": "x"}})
    agent = PlanningAgent(StubAdapter([V0_JSON]), poi_details=store)
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    host = _visit(body, "雷峰塔")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{host}/insert-alt",
        json={"name": "西湖", "day": 2, "after_item_id": None},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "duplicate_in_plan"}


def test_insert_alt_guard_chain():
    store = StubAltStore({"灵隐寺": LINGYIN})
    agent = PlanningAgent(StubAdapter([V0_JSON]), poi_details=store)
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    host = _visit(body, "雷峰塔")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{host}/insert-alt",
        json={"name": "灵隐寺", "day": 2},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "missing_device_id"}
    resp = client.post(
        "/api/v1/plan/no-such/items/v1/insert-alt",
        json={"name": "灵隐寺", "day": 2},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/v_none/insert-alt",
        json={"name": "灵隐寺", "day": 2},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "item_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{host}/insert-alt",
        json={"name": "灵隐寺", "day": 9},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "day_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{host}/insert-alt",
        json={"name": "灵隐寺", "day": 2, "after_item_id": "v_none"},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "after_not_found"}
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{host}/insert-alt",
        json={"name": "库里没有的点", "day": 2},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "no_match"}


def _one_day_session(items: list[VisitItem]) -> PlanSession:
    return PlanSession(
        session_id="s1",
        device_id="d1",
        cities=["杭州"],
        days=1,
        state="ready",
        plan=ItineraryPlan(
            itinerary_id="it_alt",
            cities=["杭州"],
            days=[DayPlan(day=1, base_city="杭州", items=list(items))],
        ),
    )


def _packed_day() -> list[VisitItem]:
    """两张钉死的大块占掉 9:00-10:30 与 13:00-17:00，尾巴上再挂一张可让位
    弱卡（tier 11，傍晚开场已过白天入场闸=反正排不上）：拖进 75' 备选后
    只有 10:30-12:00 这个空档能装它，弱卡必然让位。"""
    return [
        VisitItem(
            item_id="v1",
            name="杭州景点1",
            city="杭州",
            day=1,
            start_time=dtime(9, 0),
            end_time=dtime(10, 30),
            duration_minutes=90,
            pinned=True,
        ),
        VisitItem(
            item_id="v2",
            name="杭州景点2",
            city="杭州",
            day=1,
            start_time=dtime(13, 0),
            end_time=dtime(17, 0),
            duration_minutes=240,
            pinned=True,
        ),
        VisitItem(
            item_id="v3",
            name="杭州景点3",
            city="杭州",
            day=1,
            start_time=dtime(17, 30),
            end_time=dtime(21, 0),
            duration_minutes=210,
            tier=11,
        ),
    ]


def test_insert_alt_evicts_weakest_and_notes_it():
    agent = PlanningAgent(
        StubAdapter([]), poi_details=StubAltStore({"灵隐寺": LINGYIN})
    )
    session = _one_day_session(_packed_day())
    report, summary, notes = asyncio.run(
        agent.insert_alternative(
            session, "v1", name="灵隐寺", new_day=1, after_item_id=None
        )
    )
    day = session.plan.days[0]
    names = [i.name for i in day.items if isinstance(i, VisitItem)]
    assert "灵隐寺" in names
    # 两张钉死的卡不让位，尾巴上那张弱卡被挤掉（列表按游标时链归位）
    assert sorted(names) == sorted(["灵隐寺", "杭州景点1", "杭州景点2"])
    alt = next(i for i in day.items if getattr(i, "name", "") == "灵隐寺")
    first = next(i for i in day.items if getattr(i, "name", "") == "杭州景点1")
    assert alt.start_time is not None and alt.start_time >= first.end_time
    assert any("撤下" in n and "杭州景点3" in n for n in notes)
    assert any("撤下" in a for a in session.plan.assumptions)
    # 让位件留在可替换候选（H5 亮「想去」chip，可再拖回）
    assert {c.name for c in session.plan.unplaced} >= {"杭州景点3"}
    # 时链没有无时刻卡（收拾干净才落单）
    assert all(i.start_time is not None for i in day.items if isinstance(i, VisitItem))


def test_insert_alt_keeps_meal_card_window():
    """餐卡是槽位（2026-11-13 拍板）：拖入时只清可动景点时刻，午饭卡原卡窗
    保留当固定锚——2026-11-14 真机实录里餐厅被清→自愈另起占位卡→和刚拖进
    来的卡时段重叠。"""
    agent = PlanningAgent(
        StubAdapter([]), poi_details=StubAltStore({"灵隐寺": LINGYIN})
    )
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        city="杭州",
        day=1,
        start_time=dtime(12, 30),
        end_time=dtime(13, 30),
        duration_minutes=60,
        category="food",
        soft_pin=True,
    )
    night = VisitItem(
        item_id="hotel-night-d1",
        name="回酒店·夜间休息",
        city="杭州",
        day=1,
        start_time=dtime(21, 0),
        end_time=dtime(22, 0),
        duration_minutes=60,
        category="hotel",
        soft_pin=True,
    )
    park = VisitItem(
        item_id="v1",
        name="灵隐飞来峰景区",
        city="杭州",
        day=1,
        start_time=dtime(9, 0),
        end_time=dtime(12, 0),
        duration_minutes=180,
        tier=3,
    )
    session = _one_day_session([park, lunch, night])
    asyncio.run(
        agent.insert_alternative(
            session, "v1", name="灵隐寺", new_day=1, after_item_id=None
        )
    )
    day = session.plan.days[0]
    kept = next(i for i in day.items if i.item_id == "food-lunch-ph-d1")  # 卡没被删
    assert kept.start_time is not None and kept.end_time is not None
    # 卡仍落在午卡窗 [11:30, 12:30] 内（占位可挪，但窗不能出）
    lunch_start = kept.start_time.hour * 60 + kept.start_time.minute
    assert 11 * 60 + 30 <= lunch_start <= 12 * 60 + 30
    alt = next(i for i in day.items if getattr(i, "name", "") == "灵隐寺")
    assert alt.start_time is not None and alt.end_time is not None
    # 新卡不压午饭卡（卡是槽位，插入就得排开）
    assert not (alt.start_time < kept.end_time and alt.end_time > kept.start_time)


def test_insert_alt_city_mismatch_rejected():
    agent = PlanningAgent(
        StubAdapter([]), poi_details=StubAltStore({"灵隐寺": LINGYIN})
    )
    # 宿主在杭州（备选同城），落点选西安那天 → 跨城闸
    host = VisitItem(item_id="v1", name="西湖", city="杭州", day=1, duration_minutes=90)
    other = VisitItem(
        item_id="v2",
        name="回民街",
        city="西安",
        day=2,
        start_time=dtime(9, 0),
        end_time=dtime(10, 30),
        duration_minutes=90,
    )
    session = PlanSession(
        session_id="s1",
        device_id="d1",
        cities=["西安"],
        days=2,
        state="ready",
        plan=ItineraryPlan(
            itinerary_id="it_alt",
            cities=["西安"],
            days=[
                DayPlan(day=1, base_city="西安", items=[host]),
                DayPlan(day=2, base_city="西安", items=[other]),
            ],
        ),
    )
    with pytest.raises(ValueError) as exc:
        asyncio.run(agent.insert_alternative(session, "v1", name="灵隐寺", new_day=2))
    assert str(exc.value) == "city_mismatch"


GONGWANGFU = {
    "source_poi_id": "5a_006",
    "name": "西城区恭王府景区",
    "city": "北京市",
    "category": "attraction",
    "address": "柳荫街甲14号",
    "opening_hours": "08:00-17:00",
    "suggested_duration_min": 120,
    "tags": ["5a"],
    "location": (116.3866, 39.9355),
}


def test_insert_alt_reuses_hidden_untimed_card_instead_of_duplicate():
    """2026-11-15 恭王府实录：出站层把无时刻卡剔除（看板看不到），备选装配
    又用剔除后的副本把同一站亮成 chip——拖进来不能报「已经有这景点」，要
    把那张隐藏卡挪到落点排期（复用，不建第二张）。"""
    agent = PlanningAgent(
        StubAdapter([]), poi_details=StubAltStore({"西城区恭王府景区": GONGWANGFU})
    )
    hidden = VisitItem(
        item_id="v9",
        name="西城区恭王府景区",
        poi_id="5a_006",
        city="北京",
        day=1,
        duration_minutes=120,
    )
    host = VisitItem(
        item_id="v1",
        name="故宫博物院",
        city="北京",
        day=2,
        start_time=dtime(9, 0),
        end_time=dtime(11, 0),
        duration_minutes=120,
    )
    session = PlanSession(
        session_id="s1",
        device_id="d1",
        cities=["北京"],
        days=2,
        state="ready",
        plan=ItineraryPlan(
            itinerary_id="it_alt",
            cities=["北京"],
            days=[
                DayPlan(day=1, base_city="北京", items=[hidden]),
                DayPlan(day=2, base_city="北京", items=[host]),
            ],
        ),
    )
    asyncio.run(
        agent.insert_alternative(
            session, "v1", name="西城区恭王府景区", new_day=2, after_item_id="v1"
        )
    )
    all_gw = [
        i
        for d in session.plan.days
        for i in d.items
        if getattr(i, "name", "") == "西城区恭王府景区"
    ]
    assert len(all_gw) == 1  # 复用同一张卡，没有建第二张
    moved = all_gw[0]
    assert moved.item_id == "v9"
    assert moved.day == 2
    assert moved.start_time is not None and moved.must


def test_replace_hidden_twin_is_merged_not_duplicate():
    """同一个根因的点击换点路径：备选把隐藏的无时刻卡亮成 chip，点它不能
    报「已经有这一站」——换入后把隐藏同名卡并掉，会话里只留一张。"""
    agent = PlanningAgent(
        StubAdapter([]), poi_details=StubAltStore({"西城区恭王府景区": GONGWANGFU})
    )
    hidden = VisitItem(
        item_id="v9",
        name="西城区恭王府景区",
        poi_id="5a_006",
        city="北京",
        day=1,
        duration_minutes=120,
    )
    host = VisitItem(
        item_id="v1",
        name="故宫博物院",
        city="北京",
        day=2,
        start_time=dtime(9, 0),
        end_time=dtime(11, 0),
        duration_minutes=120,
    )
    session = PlanSession(
        session_id="s1",
        device_id="d1",
        cities=["北京"],
        days=2,
        state="ready",
        plan=ItineraryPlan(
            itinerary_id="it_alt",
            cities=["北京"],
            days=[
                DayPlan(day=1, base_city="北京", items=[hidden]),
                DayPlan(day=2, base_city="北京", items=[host]),
            ],
        ),
    )
    asyncio.run(agent.replace_item(session, "v1", name="西城区恭王府景区"))
    names = [
        getattr(i, "name", "")
        for d in session.plan.days
        for i in d.items
        if getattr(i, "name", "")
    ]
    assert names.count("西城区恭王府景区") == 1  # 隐藏同名卡已并入
    assert "故宫博物院" not in names


def test_insert_alt_hotel_candidate_type_mismatch_422():
    """备选基本类型一致（2026-11-17 拍板）：住宿候选不能拖进时间轴当景点卡，
    422 type_mismatch（原行程不动）。"""
    store = StubAltStore(
        {
            "西湖四季酒店": {
                **LINGYIN,
                "name": "西湖四季酒店",
                "category": "hotel",
                "source_poi_id": "ct_杭州_hotel",
            }
        }
    )
    agent = PlanningAgent(StubAdapter([V0_JSON]), poi_details=store)
    client = client_for(agent)
    body = start(
        client, {"cities": ["上海", "杭州"], "days": 2, "preferences": "博物馆"}
    ).json()
    sid = body["session_id"]
    host = _visit(body, "雷峰塔")["item_id"]
    resp = client.post(
        f"/api/v1/plan/{sid}/items/{host}/insert-alt",
        json={"name": "西湖四季酒店", "day": 2, "after_item_id": host},
        headers=DEVICE_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "type_mismatch"}