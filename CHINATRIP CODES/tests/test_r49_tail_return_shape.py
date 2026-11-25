# -*- coding: utf-8 -*-
"""R49：纯打车回城腿不再携带/渲染「购票 / 接驳约 ¥0」退化接驳块。

用户实报（会话 f19b103f day3）：鸟巢卡下渲染出「🎟 购票 / 打车约 ¥29 + 接驳约
¥0」——尾站回城明细（legs._attach_plain_tail_return）把统一 schema 的接驳空槽
写成字面量空串/零值，前端购票行闸只看「费用和 >0」，纯打车腿也渲染出无信息
退化块。锁定三件事：
①后端纯打车回城 detail 的接驳槽位一律 None（不再伪造「有一段 ¥0 接驳」）；
②回城链信号（direction/to_city/时刻/打车字段）原样保留（R39d 守卫/回城卡
  投影/散场压缩都依赖它们）；
③前端购票行加 hasShuttle 渲染闸（专线名/运营方/班次/票价/接驳费任一真值才
  出），兜住存量会话里已持久化的空槽（only_missing 读路径不会重算）。
"""

from datetime import time
from pathlib import Path

from app.services.itinerary import legs as legs_mod
from app.services.itinerary.fares import estimate_taxi_fare
from app.services.itinerary.legs import annotate_legs
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

REPO = Path(__file__).resolve().parents[1]


def _v(item_id, name, lon, lat, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city="北京",
        day=1,
        duration_minutes=60,
        category="sight",
        location=GeoPoint(lon=lon, lat=lat),
        start_time=time(9, 0),
        end_time=time(16, 0),
    )
    base.update(kw)
    return VisitItem(**base)


def test_plain_tail_return_shuttle_slots_are_none():
    """末站离城锚 ≥10km、其后只有无坐标夜卡 → 命中 _attach_plain_tail_return。"""
    far = _v("far", "远郊景点", 116.4074, 40.0040)  # 距北京城心 ≈11.1km
    night = _v(
        "hotel-night-d1",
        "🏨 回酒店·夜间休息",
        0.0,
        0.0,
        category="hotel",
        location=None,
    )
    plan = ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[far, night])],
        assumptions=[],
    )
    annotate_legs(plan)
    detail = far.next_leg_detail
    assert detail, "tail return detail should be attached"
    # 回城链信号原样保留
    assert detail.get("direction") == "return"
    assert detail.get("to_city") is True
    assert legs_mod._has_return_chain(far)
    # 打车事实保留
    assert detail.get("mode") == "taxi"
    assert detail.get("taxi_km") and detail.get("taxi_km") >= 10.0
    assert detail.get("taxi_cost") == estimate_taxi_fare("北京", detail["taxi_km"]) > 0
    assert far.next_leg_cost_cny == detail.get("taxi_cost")
    # 接驳空槽一律 None（不再伪造「有一段 ¥0 接驳」）
    for key in (
        "gateway",
        "alight",
        "service_name",
        "operator",
        "departures",
        "returns",
        "fare_text",
        "access_cost",
    ):
        assert detail.get(key) is None, (
            f"slot {key} should be None, got {detail.get(key)!r}"
        )


def test_frontend_pay_gate_guard():
    """前端购票行必须挂 hasShuttle 渲染闸（兜存量会话的持久化空槽）。"""
    html = (REPO / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert html.count("const hasShuttle") == 1
    gate = "if (hasShuttle && (legD.taxi_cost || 0) + (legD.access_cost || 0) > 0) {"
    assert html.count(gate) == 1


def test_backend_taxi_detail_source_guard():
    """legs.py 纯打车回城明细不得再写字面量空串/零值接驳槽。"""
    src = (REPO / "app" / "services" / "itinerary" / "legs.py").read_text(
        encoding="utf-8"
    )
    assert '"access_cost": 0,' not in src
    assert '"access_cost": None,' in src
    assert '"service_name": "",' not in src
    assert '"service_name": None,' in src
    assert '"departures": [],' not in src
