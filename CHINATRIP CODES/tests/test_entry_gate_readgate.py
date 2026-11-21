"""白天入场闸读闸测试（2026-11-17 二拍「CAN WE FIX THE REMAINING ONE」）。

两层：
- 单元：enforce_entry_gate 对越闸非钉普通观光卡退回无时刻+披露，
  豁免面（餐宿/夜属性/钉住）不动、幂等；
- 接线：真实 GET 出站闸（_plan_turn_body）上越闸卡被清时刻、披露进
  响应 plan.assumptions（照 test_plan_contract 的离线确定性模式）。
"""

from datetime import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.plan import get_plan_sessions, get_planning_agent, router
from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    PlanSessionStore,
    enforce_entry_gate,
)
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem


def _item(
    iid,
    name,
    start=None,
    end=None,
    *,
    dur=90,
    category="attraction",
    bvt=None,
    pinned=False,
    poi_id=None,
    opening_hours=None,
):
    return VisitItem(
        item_id=iid,
        name=name,
        city="上海",
        day=1,
        start_time=time.fromisoformat(start) if start else None,
        end_time=time.fromisoformat(end) if end else None,
        duration_minutes=dur,
        category=category,
        best_visit_time=bvt,
        pinned=pinned,
        poi_id=poi_id,
        opening_hours=opening_hours,
    )


def _plan(*items):
    day = DayPlan(day=1, base_city="上海", items=list(items))
    return ItineraryPlan(itinerary_id="it-gate", cities=["上海"], days=[day])


# --- 单元层 ------------------------------------------------------------------


def test_after_gate_sight_goes_untimed_with_note():
    # R12-H23：>16:30（16:00 帽+30 弹性）才移出
    plan = _plan(
        _item(
            "v1",
            "静安寺",
            "16:45",
            "18:15",
            dur=90,
            poi_id="jas",
            opening_hours="周一至周日 07:30-18:00",
        )
    )
    notes = enforce_entry_gate(plan)
    card = plan.days[0].items[0]
    assert card.start_time is None and card.end_time is None
    assert notes and "静安寺" in notes[0] and "入场" in notes[0]


def test_big_site_15_30_band():
    # 120 分钟大点 16:35 开场 → 越 15:30 大点开场带 65 分钟（>30 容忍）
    plan = _plan(
        _item(
            "v1",
            "上海中心大厦",
            "16:35",
            "18:35",
            dur=120,
            category="viewpoint",
            poi_id="tower",
            opening_hours="周一至周日 08:30-22:00 最晚进入21:30",
        )
    )
    notes = enforce_entry_gate(plan)
    assert plan.days[0].items[0].start_time is None
    assert notes


def test_entry_gate_tolerance_within_30():
    # R12-E2（2026-11-16 拍板「≤30 分钟容忍」同口径）：微越线不清时刻
    # ——大点 16:00（越 15:30 恰 30）、15:50（越 20）；普通点 16:31
    # （越 16:30 恰 1）都保留。
    plan = _plan(
        _item(
            "t1",
            "天坛",
            "15:38",
            "18:08",
            dur=150,
            category="temple",
            poi_id="tt",
            opening_hours="今天06:30-22:00开放（21:00停止入园）",
        ),
        _item(
            "t2",
            "上海中心大厦",
            "16:00",
            "18:00",
            dur=120,
            category="viewpoint",
            poi_id="tower",
            opening_hours="周一至周日 08:30-22:00 最晚进入21:30",
        ),
        _item(
            "t3",
            "小点",
            "16:31",
            "17:31",
            dur=60,
            category="park",
        ),
    )
    assert enforce_entry_gate(plan) == []
    assert all(i.start_time is not None for i in plan.days[0].items)


def test_within_gate_kept():
    plan = _plan(_item("v1", "豫园", "13:42", "15:12", dur=90, category="park"))
    assert enforce_entry_gate(plan) == []
    assert plan.days[0].items[0].start_time is not None


def test_open_form_street_after_gate_kept():
    # 2026-11-17 拍板：M50创意园/武康路类商业街 citywalk 无营业窗=
    # 开放形态，晚闸豁免——16:58 开场照排不清时刻（与出站闸
    # _evict_evening_gate_breachers 同口径）；全天窗（00:00-24:00）
    # 的新天地同理。
    plan = _plan(
        _item("m50", "M50创意园", "16:58", "19:28", dur=150, category="citywalk")
    )
    assert enforce_entry_gate(plan) == []
    assert plan.days[0].items[0].start_time is not None
    plan2 = _plan(
        _item(
            "xtd",
            "新天地",
            "17:10",
            "19:10",
            dur=120,
            category="attraction",
            poi_id="xtd",
            opening_hours="周一至周日 00:00-24:00",
        )
    )
    assert enforce_entry_gate(plan2) == []
    assert plan2.days[0].items[0].start_time is not None


def test_exempt_surface_untouched():
    plan = _plan(
        _item("f1", "晚饭（自由安排）", "19:00", "20:30", dur=90, category="food"),
        _item("h1", "回酒店·夜间休息", "21:00", "22:00", dur=60, category="hotel"),
        _item(
            "v2",
            "黄浦江游览",
            "19:15",
            "21:15",
            dur=120,
            category="theme_park",
            bvt="evening",
        ),
        _item("v3", "用户钉住", "18:00", "19:00", dur=60, pinned=True),
    )
    assert enforce_entry_gate(plan) == []
    assert all(i.start_time is not None for i in plan.days[0].items)


def test_idempotent():
    plan = _plan(
        _item(
            "v1",
            "静安寺",
            "16:45",
            "18:15",
            dur=90,
            poi_id="jas",
            opening_hours="周一至周日 07:30-18:00",
        )
    )
    first = enforce_entry_gate(plan)
    assert first
    assert enforce_entry_gate(plan) == []


# --- 接线层（GET 出站闸）-----------------------------------------------------


class _NoLLMAdapter:
    name = "stub"

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("入场闸 GET 读闸不应调 LLM")


def test_get_readgate_strips_after_gate_sight():
    agent = PlanningAgent(_NoLLMAdapter())

    async def _noop_refresh_legs(session):
        return None

    agent.refresh_legs = _noop_refresh_legs
    app = FastAPI()
    store = PlanSessionStore()
    app.dependency_overrides[get_planning_agent] = lambda: agent
    app.dependency_overrides[get_plan_sessions] = lambda: store
    app.include_router(router)
    session = PlanSession(
        session_id="s-gate",
        device_id="dev-1",
        state="ready",
        must_visits=[],
    )
    session.plan = _plan(
        _item("v0", "上午点", "09:00", "10:30", dur=90),
        _item(
            "v1",
            "静安寺",
            "16:15",
            "17:45",
            dur=90,
            poi_id="jas",
            opening_hours="周一至周日 07:30-18:00",
        ),
    )
    store.save(session)

    resp = TestClient(app).get("/api/v1/plan/s-gate", headers={"X-Device-ID": "dev-1"})
    assert resp.status_code == 200
    body = resp.json()
    days = body["plan"]["days"]
    cards = {i["name"]: i for d in days for i in d["items"]}
    assert cards["上午点"]["start_time"] is not None
    # 越闸卡：读闸退回无时刻 → 响应装配 (_strip_untimed_items) 直接不再下发
    assert "静安寺" not in cards
    assumptions = body["plan"].get("assumptions") or []
    assert any("静安寺" in a and "入场" in a for a in assumptions)
