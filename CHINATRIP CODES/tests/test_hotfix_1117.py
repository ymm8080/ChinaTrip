"""2026-11-17 incident hotfix tests (session 24379abd shape).

Covers: untimed-must demotion (B-01), fillers yield when a must is unseated
(B-02), pre-remote filler eviction + access-profile retime + lunch anchor at
the remote site (B-03), idempotency, and the wired read-gate order.
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.hotfix_1117 import (
    evict_fillers_when_must_unseated,
    evict_pre_remote_fillers,
    retime_remote_day_from_access,
)
from app.services.itinerary.legs import resolve_meal_anchors
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary.request_coverage import (
    demote_untimed_musts,
    missing_must_visits,
)

MUSTS = ["天安门广场", "故宫博物院", "慕田峪长城", "天坛", "颐和园"]


def _v(
    item_id,
    name,
    *,
    day=1,
    start=None,
    end=None,
    dur=90,
    cat="attraction",
    pinned=False,
    must=False,
    remote=False,
    loc=(116.40, 39.91),
    created=False,
    curated=False,
    soft_pin=False,
    access_deps=None,
    ride=None,
    last_mile=None,
    anchor_from_prev=False,
    anchor_loc=None,
    address=None,
    access_mode=None,
    boarding=None,
    service=None,
    wait=None,
):
    return VisitItem(
        item_id=item_id,
        name=name,
        poi_id=item_id,
        category=cat,
        city="北京",
        day=day,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        pinned=pinned,
        must=must,
        remote=remote,
        created=created,
        curated=curated,
        soft_pin=soft_pin,
        location=GeoPoint(lon=loc[0], lat=loc[1]) if loc else None,
        access_depart_times=access_deps,
        access_ride_minutes=ride,
        access_last_mile_minutes=last_mile,
        access_mode=access_mode,
        access_boarding=GeoPoint(lon=boarding[0], lat=boarding[1])
        if boarding
        else None,
        access_service_minutes=service,
        access_wait_minutes=wait,
        anchor_from_prev=anchor_from_prev,
        anchor_location=GeoPoint(lon=anchor_loc[0], lat=anchor_loc[1])
        if anchor_loc
        else None,
        address=address,
    )


def incident_plan() -> ItineraryPlan:
    """Mirrors session 24379abd: D1 天安门+老舍茶馆+午饭+慕田峪，
    D2 故宫+天坛+梵高+颐和园(灰卡)。"""
    d1 = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _v(
                "v47",
                "天安门广场",
                start=time(7, 10),
                end=time(8, 40),
                dur=90,
                pinned=True,
                must=True,
            ),
            _v(
                "extras-1-老舍茶馆",
                "老舍茶馆",
                cat="tea_experience",
                start=time(9, 10),
                end=time(10, 10),
                dur=60,
                loc=(116.393, 39.899),
            ),
            _v(
                "food-lunch-ph-d1",
                "午饭（自由安排）",
                cat="food",
                start=time(11, 38),
                end=time(12, 38),
                dur=60,
                soft_pin=True,
                anchor_from_prev=True,
                anchor_loc=(116.393, 39.899),
                loc=None,
            ),
            _v(
                "v50",
                "慕田峪长城",
                cat="historic",
                start=time(12, 38),
                end=time(15, 38),
                dur=180,
                pinned=True,
                must=True,
                remote=True,
                loc=(116.559, 40.426),
                access_deps=["07:30", "08:30", "09:30", "10:30"],
                ride=90,
                last_mile=8,
                access_mode="shuttle",
                boarding=(116.3975, 39.8997),
                service=90,
                wait=0,
                address="北京市怀柔区渤海镇慕田峪村",
            ),
            _v(
                "food-dinner-ph-d1",
                "晚饭（自由安排）",
                cat="food",
                start=time(19, 0),
                end=time(20, 30),
                dur=90,
                soft_pin=True,
                anchor_from_prev=True,
            ),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="北京",
        items=[
            _v(
                "v46",
                "故宫博物院",
                day=2,
                start=time(9, 0),
                end=time(11, 0),
                dur=120,
                pinned=True,
                must=True,
                loc=(116.409, 39.925),
            ),
            _v(
                "v48",
                "天坛",
                day=2,
                cat="temple",
                start=time(12, 0),
                end=time(14, 30),
                dur=150,
                pinned=True,
                must=True,
                loc=(116.412, 39.883),
            ),
            _v(
                "v49",
                "梵高星空艺术馆（王府井旗舰店）",
                day=2,
                cat="entertainment",
                start=time(15, 30),
                end=time(17, 0),
                dur=90,
                loc=(116.411, 39.910),
            ),
            _v(
                "food-dinner-ph-d2",
                "晚饭（自由安排）",
                day=2,
                cat="food",
                start=time(19, 0),
                end=time(20, 30),
                dur=90,
                soft_pin=True,
                anchor_from_prev=True,
            ),
            _v(
                "v51",
                "颐和园",
                day=2,
                cat="park",
                dur=300,
                pinned=True,
                must=True,
                loc=(116.274, 39.998),
            ),
        ],
    )
    return ItineraryPlan(
        itinerary_id="it-hotfix-test",
        cities=["北京"],
        days=[d1, d2],
        assumptions=[],
        unplaced=[],
    )


def run_read_gate(plan, *, lang="zh"):
    notes = []
    notes += evict_fillers_when_must_unseated(plan, must_names=MUSTS, lang=lang)
    notes += evict_pre_remote_fillers(plan, lang=lang)
    notes += retime_remote_day_from_access(plan, lang=lang)
    notes += demote_untimed_musts(plan, lang=lang)
    plan.assumptions.extend(notes)
    return notes


def test_b01_untimed_must_demoted_to_unplaced_with_disclosure():
    plan = incident_plan()
    notes = run_read_gate(plan)
    names_in_days = [i.name for d in plan.days for i in d.items]
    assert "颐和园" not in names_in_days  # grey card gone
    assert any(
        u.name == "颐和园" and u.reason == "must_unseated" for u in plan.unplaced
    )
    assert any("颐和园" in n for n in notes)
    # 三分律：全部必去 已排/想去/披露，无静默丢失
    assert missing_must_visits(plan, MUSTS) == []
    # 幂等
    assert run_read_gate(plan) == []


def test_b02_filler_yields_on_day_with_unseated_must():
    plan = incident_plan()
    run_read_gate(plan)
    d2_names = [i.name for i in plan.days[1].items]
    assert "梵高星空艺术馆（王府井旗舰店）" not in d2_names
    assert "故宫博物院" in d2_names and "天坛" in d2_names  # musts kept


def test_b03_remote_day_direct_departure_shape():
    plan = incident_plan()
    run_read_gate(plan)
    d1 = plan.days[0]
    d1_names = [i.name for i in d1.items]
    assert "老舍茶馆" not in d1_names  # pre-remote filler evicted
    assert "天安门广场" in d1_names  # morning anchor kept (must+pinned)
    mutianyu = next(i for i in d1.items if i.name == "慕田峪长城")
    lunch = next(i for i in d1.items if i.item_id == "food-lunch-ph-d1")
    # card ≡ leg: 09:30 班 + 90 ride + 8 last mile → 11:08 到站
    assert (lunch.start_time.hour, lunch.start_time.minute) == (11, 8)
    assert (lunch.end_time.hour, lunch.end_time.minute) == (12, 8)
    assert (mutianyu.start_time.hour, mutianyu.start_time.minute) == (12, 8)
    assert (mutianyu.end_time.hour, mutianyu.end_time.minute) == (15, 8)
    # lunch anchored AT the remote site, not the city teahouse
    assert lunch.anchor_location is not None
    assert abs(lunch.anchor_location.lon - 116.559) < 1e-6
    # dinner untouched (19:00)
    dinner = next(i for i in d1.items if i.item_id == "food-dinner-ph-d1")
    assert (dinner.start_time.hour, dinner.start_time.minute) == (19, 0)


def test_b03_idempotent_and_english_notes():
    plan = incident_plan()
    run_read_gate(plan)
    second = run_read_gate(plan)
    assert second == []
    plan_en = incident_plan()
    notes = run_read_gate(plan_en, lang="en")
    assert any("09:30" in n for n in notes)


def test_riding_window_lunch_not_moved():
    # 骑窗：午饭在游览中段（合法形态，不搬）；前置补点先清（读闸顺序）
    plan = incident_plan()
    evict_pre_remote_fillers(plan)
    d1 = plan.days[0]
    lunch = next(i for i in d1.items if i.item_id == "food-lunch-ph-d1")
    lunch.start_time, lunch.end_time = time(13, 0), time(14, 0)
    notes = retime_remote_day_from_access(plan)
    mutianyu = next(i for i in d1.items if i.name == "慕田峪长城")
    # visit retimed to arrival (no lunch offset); lunch stays where it was
    assert (mutianyu.start_time.hour, mutianyu.start_time.minute) == (11, 8)
    assert (lunch.start_time.hour, lunch.start_time.minute) == (13, 0)
    assert notes  # the retime note still emitted for the visit


def test_legs_lunch_anchor_prefers_remote_next_stop():
    plan = incident_plan()
    out = resolve_meal_anchors(plan)
    d1 = out.days[0]
    lunch = next(i for i in d1.items if i.item_id == "food-lunch-ph-d1")
    mutianyu = next(i for i in d1.items if i.name == "慕田峪长城")
    assert lunch.anchor_location is not None
    assert abs(lunch.anchor_location.lon - mutianyu.location.lon) < 1e-6


def test_food_cards_with_access_fields_are_not_remote():
    # 午饭/晚饭占位卡会携带相邻接驳腿字段（出班/回城）——绝不能被当
    # 成远郊点重排（复验发现的噪音源）。
    lunch_legged = _v(
        "food-lunch-ph-d1",
        "午饭（自由安排）",
        cat="food",
        start=time(11, 38),
        end=time(12, 38),
        dur=60,
        loc=None,
        anchor_from_prev=True,
        access_deps=["09:30"],
        ride=90,
        last_mile=8,
    )
    from app.services.itinerary.hotfix_1117 import _is_remote

    assert _is_remote(lunch_legged) is False
    mutianyu = _v(
        "v50",
        "慕田峪长城",
        cat="historic",
        start=time(12, 38),
        end=time(15, 38),
        dur=180,
        remote=True,
        access_deps=["09:30"],
        ride=90,
        last_mile=8,
    )
    assert _is_remote(mutianyu) is True


def test_legs_city_day_lunch_still_anchors_prev():
    plan = ItineraryPlan(
        itinerary_id="it-hotfix-test2",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    _v(
                        "extras-1-老舍茶馆",
                        "老舍茶馆",
                        cat="tea_experience",
                        start=time(9, 10),
                        end=time(10, 10),
                        dur=60,
                        loc=(116.393, 39.899),
                    ),
                    _v(
                        "food-lunch-ph-d1",
                        "午饭（自由安排）",
                        cat="food",
                        start=time(11, 30),
                        end=time(12, 0),
                        dur=30,
                        soft_pin=True,
                        anchor_from_prev=True,
                        anchor_loc=(116.393, 39.899),
                        loc=None,
                    ),
                    _v(
                        "v49",
                        "梵高星空艺术馆（王府井旗舰店）",
                        cat="entertainment",
                        start=time(15, 30),
                        end=time(17, 0),
                        dur=90,
                        loc=(116.411, 39.910),
                    ),
                ],
            )
        ],
        assumptions=[],
        unplaced=[],
    )
    out = resolve_meal_anchors(plan)
    lunch = next(i for i in out.days[0].items if i.item_id == "food-lunch-ph-d1")
    # city day: next stop is not remote → anchor stays the previous stop
    assert lunch.anchor_location is not None
    assert abs(lunch.anchor_location.lon - 116.393) < 1e-6


def test_legs_pre_remote_lunch_transparent_outbound_shuttle_restored():
    """2026-11-17 慕田峪复验案：读闸改形后去程接驳腿必须重现。

    先午餐后游览把午饭锚到远郊点、排在远郊卡之前——腿链上它必须透明，
    去程对是「天安门 → 慕田峪」（专线班次明细挂在天安门卡上），而不是
    「天安门 → 饭卡」退化成打车去远郊。午饭卡自身不吃链（同址 0 公里）。"""
    from app.services.itinerary.legs import annotate_legs

    plan = incident_plan()
    run_read_gate(plan)  # evict 老舍茶馆 + retime lunch/慕田峪
    annotate_legs(plan)
    d1 = plan.days[0]
    tiananmen = next(i for i in d1.items if i.name == "天安门广场")
    lunch = next(i for i in d1.items if i.item_id == "food-lunch-ph-d1")
    mutianyu = next(i for i in d1.items if i.name == "慕田峪长城")
    # 天安门卡挂出去程接驳链：09:30 班 → 11:08 到慕田峪（与 retime 同源）
    assert tiananmen.next_leg_mode == "access"
    detail = tiananmen.next_leg_detail or {}
    assert detail.get("next_item_id") == "v50"
    assert detail.get("depart_time") == "09:30"
    assert detail.get("arrive_time") == "11:08"
    # 同址午饭卡不吃链：没有去程腿（也没有伪打车腿）
    assert lunch.next_leg_mode is None
    assert lunch.next_leg_detail is None
    # 远郊卡回城链仍在
    assert (mutianyu.next_leg_detail or {}).get("direction") == "return"


def test_read_gate_reannotates_stale_legs_after_hotfix():
    """读闸热修动了盘面 → 腿字段按新布局重算（wiring）。

    生成期算好的腿在天安门卡上指向后来被移出的老舍茶馆（打车 1.97km）；
    _audit_must_coverage 检出 pass 有产出后重跑 annotate，旧腿被专线链
    覆写。幂等：盘面已一致（无产出）时不再重算。"""
    from app.api.plan import _audit_must_coverage
    from app.services.agent.plan import PlanSession

    session = PlanSession(
        session_id="s-hotfix-reannotate",
        device_id="d-test",
        must_visits=MUSTS,
        lang="zh",
        plan=incident_plan(),
    )
    tiananmen = next(i for i in session.plan.days[0].items if i.name == "天安门广场")
    # 生成期遗留的旧腿（指向尚未被移出的老舍茶馆）
    tiananmen.next_leg_mode = "taxi"
    tiananmen.next_leg_minutes = 30
    tiananmen.distance_to_next_km = 1.97
    tiananmen.next_leg_detail = {"mode": "taxi", "next_item_id": "extras-1-老舍茶馆"}
    _audit_must_coverage(session)
    assert tiananmen.next_leg_mode == "access"
    detail = tiananmen.next_leg_detail or {}
    assert detail.get("next_item_id") == "v50"
    assert detail.get("depart_time") == "09:30"
    # 幂等：再跑一遍不再产出、腿保持一致
    before = dict(tiananmen.next_leg_detail or {})
    _audit_must_coverage(session)
    assert tiananmen.next_leg_mode == "access"
    assert (tiananmen.next_leg_detail or {}) == before
