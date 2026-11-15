"""POI 到达方式摘要（app.services.poi_access）单测。

口径来源：2026-11-15 用户拍板「远郊景点要有交通方式（景交/地铁/火车）」，
慕田峪实测（百度 transit，城心 前门 → 景区）：单段「慕田峪长城景区直达车
前门线」，首班 07:00、末班 12:00、2 小时 8 分、下车步行 8 分钟。
"""

from __future__ import annotations

from datetime import time

from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary.rules import travel_gap_needed
from app.services.poi_access import attach_access, build_note, classify_ride, summarize


def _ride(name, kind="bus", **over):
    ride = {
        "kind": kind,
        "name": name,
        "departure_stop": None,
        "arrival_stop": None,
        "duration_s": None,
        "departure_time": None,
        "last_time": None,
        "time_table": [],
    }
    ride.update(over)
    return ride


def _plan(duration_s, *segments):
    return {"duration_s": duration_s, "segments": list(segments)}


def _ride_seg(ride):
    return {"walking": None, "rides": [ride]}


def _walk_seg(distance_m, duration_s):
    return {
        "walking": {"distance_m": distance_m, "duration_s": duration_s, "steps": []},
        "rides": [],
    }


# --- 方式判定 ------------------------------------------------------------------


def test_classify_ride_by_line_name():
    assert classify_ride(_ride("地铁8号线")) == "metro"
    assert classify_ride(_ride("慕田峪长城景区直达车前门线")) == "shuttle"
    assert classify_ride(_ride("市郊铁路怀密线")) == "train"
    assert classify_ride(_ride("120路")) == "bus"
    assert classify_ride(_ride("鼓浪屿轮渡")) == "ferry"


def test_classify_ride_falls_back_to_kind():
    assert classify_ride(_ride("", kind="railway")) == "train"
    assert classify_ride(_ride("", kind="bus")) == "bus"


# --- 摘要 ----------------------------------------------------------------------


def test_summarize_single_shuttle_keeps_first_last_and_walk():
    plans = [
        _plan(
            0,
            _walk_seg(369, 316),
            _ride_seg(
                _ride(
                    "慕田峪长城景区直达车前门线",
                    kind="bus",
                    departure_stop="前门站",
                    arrival_stop="慕田峪长城站",
                    duration_s=5546,
                    departure_time="07:00",
                    last_time="12:00",
                )
            ),
            _walk_seg(1964, 480),
        )
    ]
    plans[0]["duration_s"] = 7647
    out = summarize(plans)
    assert out is not None
    assert out["access_mode"] == "shuttle"
    assert out["access_minutes"] == 127
    assert out["access_gateway"] == "慕田峪长城站"
    # 下车点 2km 外：不再当「步行 8 分钟」报，改口接驳/打车（见下一条短步行）
    assert out["access_gateway_minutes"] is None
    assert "前门站 → 慕田峪长城站" in out["access_note"]
    assert "首班 07:00" in out["access_note"]
    assert "末班 12:00" in out["access_note"]
    assert "2.0 km" in out["access_note"]
    assert "打车/接驳" in out["access_note"]
    assert out["access_note_en"].startswith("Take 慕田峪长城景区直达车前门线")


def test_summarize_short_walk_keeps_walk_minutes():
    plans = [
        _plan(
            4200,
            _ride_seg(
                _ride(
                    "怀密线",
                    kind="railway",
                    departure_stop="黄土店站",
                    arrival_stop="雁栖湖站",
                    duration_s=3600,
                )
            ),
            _walk_seg(800, 360),
        )
    ]
    out = summarize(plans)
    assert out["access_gateway_minutes"] == 6
    assert "下车步行 6 分钟" in out["access_note"]


def test_summarize_prefers_the_ride_that_covers_the_distance():
    """地铁 40 分钟 + 长途公交 2 小时 → 报公交（远郊件问的是那趟长途车）。"""
    plans = [
        _plan(
            9600,
            _ride_seg(
                _ride(
                    "地铁2号线外环",
                    kind="railway",
                    duration_s=2400,
                    departure_stop="前门站",
                    arrival_stop="东直门站",
                )
            ),
            _walk_seg(200, 180),
            _ride_seg(
                _ride(
                    "980路快车",
                    duration_s=7200,
                    departure_stop="东直门站",
                    arrival_stop="密云站",
                )
            ),
        )
    ]
    out = summarize(plans)
    assert out is not None
    assert out["access_mode"] == "bus"
    assert "地铁2号线外环" in out["access_note"]
    assert "980路快车" in out["access_note"]
    assert "1 次换乘" in out["access_note"]


def test_summarize_marks_once_a_day_departure():
    plans = [
        _plan(
            3600,
            _ride_seg(
                _ride(
                    "密51路区间",
                    duration_s=3300,
                    departure_stop="密云站",
                    arrival_stop="沙岭七队站",
                    departure_time="11:00",
                    last_time="11:00",
                )
            ),
        )
    ]
    out = summarize(plans)
    assert "仅 11:00 一班" in out["access_note"]
    assert "首班" not in out["access_note"]


def test_summarize_picks_fastest_plan():
    slow = _plan(7200, _ride_seg(_ride("A线", duration_s=7000)))
    fast = _plan(3600, _ride_seg(_ride("B线", duration_s=3400)))
    out = summarize([slow, fast])
    assert out["access_minutes"] == 60
    assert "B线" in out["access_note"]


def test_summarize_walk_only_plan():
    out = summarize([_plan(900, _walk_seg(600, 900))])
    assert out["access_mode"] == "walk"
    assert out["access_gateway"] is None
    assert out["access_minutes"] == 15


def test_summarize_returns_none_without_usable_plan():
    assert summarize(None) is None
    assert summarize([]) is None
    assert summarize([{"duration_s": 0, "segments": []}]) is None
    assert summarize([{"segments": []}]) is None


def test_note_is_clamped_for_long_chains():
    rides = [
        _ride(
            f"线路{i}",
            departure_stop=f"站{i}",
            arrival_stop=f"站{i + 1}",
            duration_s=600,
        )
        for i in range(6)
    ]
    zh, en = build_note(rides, total_minutes=200, walk_minutes=12, gateway="终点站")
    assert len(zh) <= 300 and len(en) <= 300
    assert "…" in zh


# --- 引擎接驳腿（2026-11-15「一般是 TAXI + 引擎接驳腿」）-------------------------


def _visit(item_id, name, lon, lat, **over):
    return VisitItem(
        item_id=item_id,
        name=name,
        city="北京",
        day=1,
        location=GeoPoint(lon=lon, lat=lat),
        **over,
    )


def test_attach_access_fills_only_scheduled_sites():
    plan = ItineraryPlan(
        itinerary_id="it-1",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    _visit("v1", "慕田峪长城", 116.5598, 40.4267),
                    _visit("v2", "故宫博物院", 116.3972, 39.9163),
                ],
            )
        ],
    )
    profiles = {
        ("北京", "慕田峪长城"): {
            "access_mode": "shuttle",
            "access_boarding_lon": 116.4046,
            "access_boarding_lat": 39.9052,
            "access_service_minutes": 92,
            "access_wait_minutes": 5,
            "access_last_mile_minutes": 8,
        },
        ("北京", "故宫博物院"): {"access_mode": "metro"},
    }
    assert attach_access(plan, profiles) == 1
    mty, gugong = plan.days[0].items
    assert mty.access_mode == "shuttle"
    assert mty.access_boarding is not None
    assert mty.access_service_minutes == 92
    assert gugong.access_mode is None  # 地铁点继续走打车模型，卡片零变化


def test_attach_access_skips_profile_without_boarding_point():
    plan = ItineraryPlan(
        itinerary_id="it-2",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[_visit("v1", "慕田峪长城", 116.5598, 40.4267)],
            )
        ],
    )
    profiles = {
        ("北京", "慕田峪长城"): {"access_mode": "train", "access_service_minutes": 60}
    }
    assert attach_access(plan, profiles) == 0
    assert plan.days[0].items[0].access_mode is None


def test_travel_gap_uses_gateway_chain_for_scheduled_site():
    hotel = _visit("a", "酒店", 116.4074, 39.9042)
    mty = _visit(
        "b",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.4046, lat=39.9052),
        access_service_minutes=92,
        access_wait_minutes=5,
        access_last_mile_minutes=8,
    )
    plain = _visit("c", "慕田峪长城", 116.5598, 40.4267)
    chain = travel_gap_needed(hotel, mty)
    taxi_only = travel_gap_needed(hotel, plain)
    assert taxi_only is not None
    assert chain > taxi_only, "接驳链应比纯打车长（专线 92 分钟 + 候车 + 落客）"
    assert chain >= 92 + 5 + 8


def test_travel_matrix_uses_chain_when_access_profile_is_passed():
    """矩阵层同一口径：不打车直达，按接驳链给 solver 供值。"""
    from app.services.agent.plan import _travel_matrix

    plan = ItineraryPlan(
        itinerary_id="it-3",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    _visit("h", "王府井酒店", 116.4109, 39.9097),
                    _visit("m", "慕田峪长城", 116.5598, 40.4267),
                ],
            )
        ],
    )
    profiles = {
        ("北京", "慕田峪长城"): {
            "access_mode": "shuttle",
            "access_boarding_lon": 116.398256,
            "access_boarding_lat": 39.898886,
            "access_service_minutes": 108,
            "access_wait_minutes": 10,
            "access_last_mile_minutes": 8,
        }
    }
    plain = _travel_matrix(plan, None, None)[("h", "m")]
    chained = _travel_matrix(plan, None, profiles)[("h", "m")]
    assert plain >= 30
    assert chained > plain
    assert chained >= 108 + 10 + 8


def test_travel_gap_reads_city_profile_when_card_has_no_fields(monkeypatch):
    """心愿快路径/兜底重排不经过矩阵：卡上没字段时按库内档案查一次。"""
    import app.services.poi_access as pa

    monkeypatch.setattr(
        pa,
        "profile_for",
        lambda city, name: (
            {
                "access_mode": "shuttle",
                "access_boarding_lon": 116.398256,
                "access_boarding_lat": 39.898886,
                "access_service_minutes": 108,
                "access_wait_minutes": 10,
                "access_last_mile_minutes": 8,
            }
            if name == "慕田峪长城"
            else None
        ),
    )
    hotel = _visit("a", "王府井酒店", 116.4109, 39.9097)
    mty = _visit("b", "慕田峪长城", 116.5598, 40.4267)
    chain = travel_gap_needed(hotel, mty)
    assert chain is not None and chain >= 126


def test_head_chain_minutes_uses_city_center_proxy():
    item = _visit(
        "m",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.398256, lat=39.898886),
        access_service_minutes=108,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
    )
    from app.services.poi_access import head_chain_minutes

    head = head_chain_minutes(item)
    assert head is not None and head >= 126  # 候车 10 + 车上 108 + 落客 8 起


def test_morning_slot_pushes_first_scheduled_visit_after_chain():
    from app.services.agent.hotel_stays import _open_morning_slot

    mty = _visit(
        "m",
        "慕田峪长城",
        116.5598,
        40.4267,
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.398256, lat=39.898886),
        access_service_minutes=108,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
    )
    mty.start_time = time(8, 30)
    mty.end_time = time(12, 0)
    mty.duration_minutes = 210
    after = _visit("n", "午饭（自由安排）", 116.5598, 40.4267)
    after.start_time = time(12, 0)
    after.end_time = time(13, 0)
    after.duration_minutes = 60
    day = DayPlan(day=2, base_city="北京", items=[mty, after])
    assert _open_morning_slot(day) is True
    assert mty.start_time >= time(10, 30)  # 08:30 + 接驳链（≥126 分钟）
    assert after.start_time >= mty.end_time


def test_fallback_clamps_scheduled_gap_after_soft_lunch(monkeypatch):
    """兜底/加卡路径收口：午饭后到班次点必须留够接驳链，不再 30 分钟。"""
    import app.services.poi_access as pa
    from app.services.agent import plan as plan_mod
    from app.services.itinerary.models import time as _t

    monkeypatch.setattr(
        pa,
        "profile_for",
        lambda city, name: (
            {
                "access_mode": "shuttle",
                "access_boarding_lon": 116.398256,
                "access_boarding_lat": 39.898886,
                "access_service_minutes": 108,
                "access_wait_minutes": 10,
                "access_last_mile_minutes": 8,
            }
            if name == "慕田峪长城"
            else None
        ),
    )
    lunch = _visit("lunch", "午饭（自由安排）", 116.4109, 39.9097)
    lunch.category = "food"
    lunch.soft_pin = True
    lunch.start_time = _t(12, 0)
    lunch.end_time = _t(13, 0)
    lunch.duration_minutes = 60
    mty = _visit("mty", "慕田峪长城", 116.5598, 40.4267)
    mty.duration_minutes = 180
    am = _visit("am", "恭王府", 116.3833, 39.9322)
    am.start_time = _t(8, 30)
    am.end_time = _t(10, 30)
    am.duration_minutes = 120
    day = DayPlan(day=1, base_city="北京", items=[am, lunch, mty])
    plan = ItineraryPlan(itinerary_id="it-4", cities=["北京"], days=[day])
    plan_mod._fallback_sequence_times(plan, keep_list_order=True)
    start = mty.start_time.hour * 60 + mty.start_time.minute
    end_prev = lunch.end_time.hour * 60 + lunch.end_time.minute
    assert start >= end_prev + 120  # 候车 10 + 车上 108 + 落客 8 的下界


def test_clamp_repacks_later_cards_without_pushing_dinner(monkeypatch):
    """收口用最小重排：慕田峪后移，晚饭不该被等量推 112 分钟。"""
    import app.services.poi_access as pa
    from app.services.agent import plan as plan_mod
    from app.services.itinerary.models import time as _t

    profile = {
        "access_mode": "shuttle",
        "access_boarding_lon": 116.398256,
        "access_boarding_lat": 39.898886,
        "access_service_minutes": 108,
        "access_wait_minutes": 10,
        "access_last_mile_minutes": 8,
    }
    monkeypatch.setattr(
        pa,
        "profile_for",
        lambda city, name: profile if name == "慕田峪长城" else None,
    )

    lunch = _visit("lunch", "午饭（自由安排）", 116.4109, 39.9097)
    lunch.category = "food"
    lunch.soft_pin = True
    lunch.start_time = _t(12, 0)
    lunch.end_time = _t(13, 0)

    mty = _visit("mty", "慕田峪长城", 116.5598, 40.4267)
    mty.start_time = _t(13, 30)
    mty.end_time = _t(17, 30)
    mty.duration_minutes = 240

    dinner = _visit("dinner", "晚饭（自由安排）", 116.4109, 39.9097)
    dinner.category = "food"
    dinner.soft_pin = True
    dinner.start_time = _t(19, 0)
    dinner.end_time = _t(20, 30)

    day = DayPlan(day=1, base_city="北京", items=[lunch, mty, dinner])
    plan = ItineraryPlan(itinerary_id="it-5", cities=["北京"], days=[day])
    plan_mod._clamp_chain_gaps(plan)

    start = mty.start_time.hour * 60 + mty.start_time.minute
    dinner_start = dinner.start_time.hour * 60 + dinner.start_time.minute
    assert start >= 15 * 60 + 20, "慕田峪 应按链值后移到 15:22 之后"
    assert dinner_start <= 19 * 60 + 40, "晚饭只该让位到 19:40 以内"


def test_meal_before_chain_site_keeps_remote_transfer(monkeypatch):
    """午饭 12:00-13:00 → 慕田峪 13:30 必须按接驳链顺延（终装餐腿 + 收口两道）。"""
    import app.services.poi_access as pa
    from app.services.agent import plan as plan_mod
    from app.services.itinerary.models import time as _t

    profile = {
        "access_mode": "shuttle",
        "access_boarding_lon": 116.398256,
        "access_boarding_lat": 39.898886,
        "access_service_minutes": 108,
        "access_wait_minutes": 10,
        "access_last_mile_minutes": 8,
    }
    monkeypatch.setattr(
        pa,
        "profile_for",
        lambda city, name: profile if name == "慕田峪长城" else None,
    )

    lunch = _visit("lunch", "午饭（自由安排）", 116.4109, 39.9097)
    lunch.location = None  # 占位餐卡：只有名字没有坐标（线上真实形态）
    lunch.category = "food"
    lunch.soft_pin = True
    lunch.start_time = _t(12, 0)
    lunch.end_time = _t(13, 0)
    lunch.duration_minutes = 60

    mty = _visit("mty", "慕田峪长城", 116.5598, 40.4267)
    mty.city = "北京"
    mty.start_time = _t(13, 30)
    mty.end_time = _t(17, 30)
    mty.duration_minutes = 240

    dinner = _visit("dinner", "晚饭（自由安排）", 116.4109, 39.9097)
    dinner.location = None
    dinner.category = "food"
    dinner.soft_pin = True
    dinner.start_time = _t(19, 0)
    dinner.end_time = _t(20, 30)
    dinner.duration_minutes = 90

    day = DayPlan(day=2, base_city="北京", items=[lunch, mty, dinner])
    plan = ItineraryPlan(itinerary_id="it-6", cities=["北京"], days=[day])

    plan_mod._open_meal_leg_gaps(plan)
    plan_mod._clamp_chain_gaps(plan)

    meal_end = lunch.end_time.hour * 60 + lunch.end_time.minute
    start = mty.start_time.hour * 60 + mty.start_time.minute
    assert start - meal_end >= 140, "午饭→慕田峪 必须留够接驳链（约 142 分钟）"
