# -*- coding: utf-8 -*-
"""R39 (2026-11-25): one transit-leg format, and legs at the hotel boundary.

User reports (live Day1: 酒店 → 颐和园 → 听鹂馆):
1. Three different on-screen leg shapes for the same kind of transfer (card
   footer text / timeline bridge card / structured "打车 … → 下一站" row).
   Every transfer must render as ONE row carrying the same fields — that
   needs the bridge card to carry the footer's leg fields (distance / mode /
   minutes / fare), which it never had.
2. "DAY1 FROM HOTEL TO SITE 1 颐和园, NO TRANSPORTATION LEG" — the morning
   hotel card is a placeholder without coordinates, so ``leg_pairs`` skipped
   it and the hotel boundary never produced a leg at all.
"""

from __future__ import annotations

from datetime import time

import pytest

from app.services.itinerary.legs import annotate_legs, leg_pairs
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.trip_solver.assembly.bridges import attach_gap_bridges

# 颐和园 / 天坛 coordinates (straight-line distance from the 北京 anchor
# 39.9042,116.4074 is ~13-14 km and ~4-5 km respectively).
SUMMER_PALACE = (116.27, 39.99)
TEMPLE_OF_HEAVEN = (116.41, 39.88)
REMOTE = (116.57, 40.43)  # 慕田峪一带


def _v(item_id, name, start, end, *, cat="attraction", city="北京", loc=None, **kw):
    dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return VisitItem(
        item_id=item_id,
        name=name,
        city=city,
        day=1,
        category=cat,
        duration_minutes=kw.pop("dur", dur),
        location=GeoPoint(lon=loc[0], lat=loc[1]) if loc else None,
        start_time=start,
        end_time=end,
        **kw,
    )


def _morning(start=time(8, 30), city="北京", loc=None):
    return _v(
        "hotel-morning-d1",
        "从酒店出发",
        start,
        start,
        cat="hotel",
        city=city,
        loc=loc,
        dur=0,
    )


def _plan(items):
    return ItineraryPlan(
        itinerary_id="t39",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=items)],
        assumptions=[],
    )


def _ids(plan):
    return [(a.item_id, b.item_id) for a, b, _km in leg_pairs(plan)]


# ---------------------------------------------------------------------------
# 2) hotel boundary: morning card departs, evening card stays transparent
# ---------------------------------------------------------------------------


def test_hotel_morning_becomes_departure_card_with_city_anchor():
    plan = _plan(
        [
            _morning(),
            _v("s1", "颐和园", time(9, 20), time(11, 55), loc=SUMMER_PALACE),
        ]
    )
    assert _ids(plan) == [("hotel-morning-d1", "s1")]
    annotate_legs(plan)
    leg = plan.days[0].items[0]
    assert leg.next_leg_mode == "taxi"
    # 出发点=北京城市锚（39.9042, 116.4074）——直线距离按同一公式算，不靠手算常数
    from app.services.itinerary.rules import haversine_km

    expect_km = haversine_km(
        GeoPoint(lon=116.4074, lat=39.9042),
        GeoPoint(lon=SUMMER_PALACE[0], lat=SUMMER_PALACE[1]),
    )
    assert leg.distance_to_next_km == pytest.approx(expect_km, abs=0.01)
    assert expect_km > 10  # 确实是从市中心到颐和园的量级，不是同址
    assert isinstance(leg.next_leg_minutes, int) and leg.next_leg_minutes > 0
    assert isinstance(leg.next_leg_cost_cny, (int, float))
    assert leg.next_walk_minutes is not None  # H5 footer gate


def test_real_hotel_coordinates_win_over_city_anchor():
    far = (116.85, 40.05)  # a real hotel far out east
    plan = _plan(
        [
            _morning(loc=far),
            _v("s1", "颐和园", time(9, 20), time(11, 55), loc=SUMMER_PALACE),
        ]
    )
    ((_a, _b, km),) = leg_pairs(plan)
    assert km == pytest.approx(51.0, abs=3.0)  # not the 13.9 km city-anchor figure


def test_hotel_morning_to_scheduled_remote_gets_access_chain():
    """占位晨卡 → 远郊班次点：成对并出接驳链（不是直线打车腿）。

    晨卡位置（城市锚）写回 anchor_location 后，access_breakdown 的起点取得到，
    算得出「打车到乘车点 + 候车 + 专线」链——与带锚晨卡（test_leg_fares 三条）
    同形，不需要任何特判。
    """
    plan = _plan(
        [
            _morning(),
            _v(
                "r1",
                "慕田峪长城",
                time(10, 40),
                time(14, 40),
                loc=REMOTE,
                access_mode="shuttle",
                access_service_minutes=90,
                access_boarding_stop="前门大街北口",
                access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
            ),
        ]
    )
    assert _ids(plan) == [("hotel-morning-d1", "r1")]
    annotate_legs(plan)
    leg = plan.days[0].items[0]
    assert leg.next_leg_mode == "access"
    assert (leg.next_leg_detail or {}).get("direction") != "return"


def test_hotel_night_card_stays_transparent():
    # 末站→夜卡不在这里成对（回城链/回城卡口径不动）。
    plan = _plan(
        [
            _v("s1", "天坛", time(9, 0), time(11, 0), loc=TEMPLE_OF_HEAVEN),
            _v(
                "hotel-night-d1",
                "回酒店·夜间休息",
                time(21, 0),
                time(21, 30),
                cat="hotel",
            ),
        ]
    )
    assert _ids(plan) == []


def test_remote_last_stop_return_chain_untouched():
    # 末站是班次点：回城三段链照旧挂上（城市锚回退没有碰 _point）。
    plan = _plan(
        [
            _v(
                "r1",
                "慕田峪长城",
                time(10, 40),
                time(14, 40),
                loc=REMOTE,
                access_mode="shuttle",
                access_service_minutes=90,
                access_last_mile_minutes=8,
                access_boarding_stop="前门大街北口",
                access_alight_stop="前门大街北口",
                access_boarding=GeoPoint(lon=116.397, lat=39.899),
                access_return_times=["14:30", "15:30", "16:30"],
            ),
            _v(
                "hotel-night-d1",
                "回酒店·夜间休息",
                time(21, 0),
                time(21, 30),
                cat="hotel",
            ),
        ]
    )
    annotate_legs(plan)
    site = plan.days[0].items[0]
    assert site.next_leg_mode == "access"
    assert (site.next_leg_detail or {}).get("direction") == "return"


# ---------------------------------------------------------------------------
# 1) bridge card carries the same leg fields as the card footer
# ---------------------------------------------------------------------------


def _two_site_plan(tail=False):
    items = [
        _v("s1", "天坛", time(9, 0), time(11, 0), loc=TEMPLE_OF_HEAVEN),
        _v("s2", "颐和园", time(12, 30), time(15, 0), loc=SUMMER_PALACE),
    ]
    if tail:
        items.append(
            _v(
                "hotel-night-d1",
                "回酒店·夜间休息",
                time(21, 0),
                time(21, 30),
                cat="hotel",
            )
        )
    return _plan(items)


def _bridge(plan):
    return next(
        (
            i
            for i in plan.days[0].items
            if str(i.item_id or "").startswith("leg-bridge-")
        ),
        None,
    )


def test_bridge_card_inherits_annotated_leg_fields():
    plan = _two_site_plan()
    annotate_legs(plan)
    src = plan.days[0].items[0]
    attach_gap_bridges(plan)
    br = _bridge(plan)
    assert br is not None
    assert br.distance_to_next_km == src.distance_to_next_km
    assert br.next_leg_mode == src.next_leg_mode
    assert br.next_leg_minutes == src.next_leg_minutes
    assert br.next_leg_cost_cny == src.next_leg_cost_cny
    assert br.next_walk_minutes is not None
    # 名字不带目的地名（既有口径不动）
    assert "颐和园" not in (br.name or "")


def test_bridge_card_estimates_when_prev_has_no_annotated_leg():
    plan = _two_site_plan()
    # 不跑 annotate：前卡没有腿字段，桥卡按坐标+价目表现估
    attach_gap_bridges(plan)
    br = _bridge(plan)
    assert br is not None
    assert br.distance_to_next_km == pytest.approx(16.5, abs=1.5)
    assert br.next_leg_mode in ("taxi", "walk")
    assert isinstance(br.next_leg_minutes, int) and br.next_leg_minutes > 0
    if br.next_leg_mode == "taxi":
        assert isinstance(br.next_leg_cost_cny, (int, float))


def test_bridge_card_leaves_fields_empty_without_coordinates():
    plan = _plan(
        [
            _v("s1", "甲", time(9, 0), time(11, 0)),
            _v("s2", "乙", time(12, 30), time(15, 0)),
        ]
    )
    attach_gap_bridges(plan)
    br = _bridge(plan)
    assert br is not None
    assert br.distance_to_next_km is None
    assert br.next_leg_minutes is None


def test_h5_unified_leg_row_wiring_and_syntax(tmp_path):
    """H5 守门：统一腿行的接线在位，且内联脚本语法成立。

    站间交通腿只许一种呈现——[出发时刻] 距下一站 X km · 车程/步行/接驳约
    N 分钟 · 约 ¥Y，行右 TAXI + ALL TRANSPORTATION。接线断言守住三件事：
    页脚只在「没有紧跟桥卡」时出、桥卡卡名位走同一构造器、回程结构化块里
    与页脚重复的打车行让位。内联脚本逐块过 ``node --check``——R39 实锤：
    整段替换吃掉了一个 ``if`` 开括号，只有语法检查能在提交前抓住。
    """
    import re
    import shutil
    import subprocess
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "app" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")

    assert "function legRowParts(it, items, idx) {" in html
    assert "function navAllTransportTo(name, lon, lat) {" in html
    assert "if (hasKm && !isBridgeCard && !bridgeFollows) {" in html  # 页脚闸
    assert "const brRow = isBridgeCard ? legRowParts(it, d.items, idx) : null;" in html
    assert "if (isRet && !hasKm && (Number(legD.taxi_km) || 0) > 0.05) {" in html
    # 页脚：出发时刻在前、按钮在右
    assert (
        '\'<span class="t" style="flex:0 0 auto">\' + fmtTime(it.end_time) + "</span>"'
        in html
    )
    assert (
        "'<span style=\"flex:0 0 auto;margin-left:auto;white-space:nowrap\">'"
        " + rowParts.buttons" in html
    )
    # 按钮与跳转：TAXI 复用 calltaxi；ALL TRANSPORTATION 落导航页
    # （起点=当前位置、终点=下一景点）
    assert 'button[data-action="navall"]' in html
    assert 'navAllTransportTo(na.getAttribute("data-name")' in html
    assert '#modeBar button[data-mode="driving"]' in html

    i18n = (static / "i18n.js").read_text(encoding="utf-8")
    assert '"card.allTransport": "🧭 ALL TRANSPORTATION"' in i18n
    assert '"card.allTransport.title": "Open the Navigation tab' in i18n

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH — inline script syntax not checked")
    targets = []
    for m in re.finditer(
        r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", html, flags=re.S
    ):
        attrs = m.group("attrs") or ""
        if re.search(r"\bsrc\s*=", attrs) or "json" in attrs:
            continue
        f = tmp_path / ("inline_%d.js" % len(targets))
        f.write_text(m.group("body"), encoding="utf-8")
        targets.append(f)
    for name in ("sw.js", "i18n.js"):
        targets.append(static / name)
    assert targets, "no inline script block found"
    for f in targets:
        r = subprocess.run(
            [node, "--check", str(f)], capture_output=True, text=True, encoding="utf-8"
        )
        assert r.returncode == 0, "%s: %s" % (f.name, (r.stderr or "")[:400])


def test_morning_with_anchor_keeps_access_chain_to_scheduled_stop():
    """晨卡自带锚点（location=None + anchor_location=城市锚）→ 远郊班次点：基线就成对
    出接驳链（test_leg_fares 三条的形状）。「不叠直线腿」只约束自身无坐标/锚点、
    位置靠城市锚回退的占位晨卡——第一版规则连带锚晨卡一起跳掉，把这三条打红。"""
    morning = _v(
        "hotel-morning-d1",
        "从酒店出发",
        time(8, 30),
        time(9, 0),
        cat="hotel",
        dur=0,
        anchor_location=GeoPoint(lon=116.4074, lat=39.9042),
    )
    plan = _plan(
        [
            morning,
            _v(
                "r1",
                "慕田峪长城",
                time(10, 40),
                time(14, 40),
                loc=REMOTE,
                access_mode="shuttle",
                access_service_minutes=90,
                access_boarding_stop="前门大街北口",
                access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
            ),
        ]
    )
    assert _ids(plan) == [("hotel-morning-d1", "r1")]
    annotate_legs(plan)
    leg = plan.days[0].items[0]
    assert leg.next_leg_mode == "access"
    assert (leg.next_leg_detail or {}).get("direction") != "return"


def test_hotel_morning_position_written_back_to_anchor_location():
    """leg_pairs 的契约：成对的卡必有取值点（location 或 anchor_location）。

    R39 线上 500 实锤：晨卡位置只在链内用城市锚算、没写回卡上——读路径
    _enrich_legs 对成对前卡取 _leg_point(a).lon 做图商实测回填，拿到 None
    直接 AttributeError，带无坐标晨卡的会话 GET /plan 全部 500。
    """
    from app.services.agent.plan import _leg_point

    plan = _plan(
        [_morning(), _v("s1", "颐和园", time(9, 20), time(11, 55), loc=SUMMER_PALACE)]
    )
    assert _ids(plan) == [("hotel-morning-d1", "s1")]
    morning = plan.days[0].items[0]
    assert morning.location is None  # 占位晨卡没有真坐标
    assert morning.anchor_location is not None  # 城市锚写回卡上
    assert _leg_point(morning) is not None


def test_get_plan_with_coordless_morning_card_does_not_500():
    """读盘路径回归（R39 线上 500 实锤）：agent 带 amap（生产形态）时，

    无坐标晨卡的会话 GET /api/v1/plan/{sid} 必须 200，且晨卡带出到第一个
    景点的腿。测试环境默认没有 amap，_enrich_legs 开头就 return——必须显式
    挂一个 amap stub 才覆盖得到炸点。
    """
    from fastapi.testclient import TestClient

    from app.api.plan import get_plan_sessions
    from app.services.agent.plan import PlanningAgent, PlanSession
    from tests.test_plan_api import StubAdapter, make_app

    class _Amap:
        vendor = "stub"

        async def walking_route(
            self, origin, destination, *, origin_id=None, destination_id=None
        ):
            return {"distance_m": 16000, "duration_s": 32 * 60}

    agent = PlanningAgent(StubAdapter([]))
    agent._amap = _Amap()
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    store.save(
        PlanSession(
            session_id="s-r39-morning",
            device_id="device-r39",
            state="ready",
            plan=ItineraryPlan(
                itinerary_id="it-r39",
                cities=["北京"],
                days=[
                    DayPlan(
                        day=1,
                        base_city="北京",
                        items=[
                            _morning(),
                            _v(
                                "s1",
                                "颐和园",
                                time(9, 20),
                                time(11, 55),
                                loc=SUMMER_PALACE,
                            ),
                        ],
                    )
                ],
            ),
        )
    )
    with TestClient(app, headers={"X-Device-ID": "device-r39"}) as client:
        r = client.get("/api/v1/plan/s-r39-morning")
    assert r.status_code == 200, r.text
    items = {i["item_id"]: i for i in r.json()["plan"]["days"][0]["items"]}
    assert items["hotel-morning-d1"]["distance_to_next_km"] is not None
