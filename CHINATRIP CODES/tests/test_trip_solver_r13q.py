"""R13q: CP-SAT 餐饮候选搜索补位 + 城际腿真实班次回填。

两条挂账的回归闸：
- gap #1: prefetch_food_rows → snapshot candidates（food/any-槽），
  无 food_rows 时快照形状完全不变（影子语料零漂移）；
- gap #2: fill_structural_leg_numbers 只回填引擎自造的无号腿，
  用户已填号码绝不覆盖，查询失败保留占位卡。
"""

from __future__ import annotations

from datetime import time

import pytest

from app.services.itinerary.models import DayPlan, ItineraryPlan, TransferItem
from app.services.trip_solver.enrich_food import prefetch_food_rows
from app.services.trip_solver.leg_numbers import fill_structural_leg_numbers
from app.services.trip_solver.live import snapshot_from_request


class _FakeStore:
    def recommendation_food_in_city(self, city, limit=10):
        return [
            {
                "name": "四季民福烤鸭店",
                "source_poi_id": "f-001",
                "category": "food",
                "city": city,
                "address": "故宫店",
                "opening_hours": "10:00-22:00",
                "rating": 4.7,
                "location": (116.4, 39.9),
                "tags": ["curated"],
                "rec_tagged": True,
            }
        ]


class _EmptyStore:
    def __init__(self):
        self.calls = 0

    def top_pois_in_city(self, city, limit=30):
        self.calls += 1
        return []

    def recommendation_food_in_city(self, city, limit=10):
        return []


class _FakeTrain:
    async def search(self, from_city, to_city, date):
        from app.services.trains import TrainOption

        return [
            TrainOption(
                train_no="G9",
                dep_time=time(9, 0),
                arr_time=time(14, 0),
                duration_minutes=300,
                from_station="北京南",
                to_station="上海虹桥",
                from_city=from_city,
                to_city=to_city,
                date=date,
            )
        ]


@pytest.mark.asyncio
async def test_prefetch_food_rows_db_only_no_amap():
    rows = await prefetch_food_rows(
        cities=["北京"], amap_client=None, store=_FakeStore(), enabled=True
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "四季民福烤鸭店"
    assert rows[0]["meal_slot"] == "any"


@pytest.mark.asyncio
async def test_prefetch_food_rows_disabled_is_zero_io():
    rows = await prefetch_food_rows(
        cities=["北京"], amap_client=object(), store=_FakeStore(), enabled=False
    )
    assert rows == []


def test_food_rows_join_snapshot_as_food_any_slot():
    row = {
        "name": "四季民福烤鸭店",
        "source_poi_id": "f-001",
        "category": "food",
        "city": "北京",
        "location": (116.4, 39.9),
    }
    kwargs = dict(cities=["北京"], days=1, start_date="2026-11-24", musts=[])
    base = snapshot_from_request(store=_EmptyStore(), **kwargs)
    enriched = snapshot_from_request(store=_EmptyStore(), food_rows=[row], **kwargs)
    assert len(enriched.candidates) == len(base.candidates) + 1
    cand = next(c for c in enriched.candidates if c.name == row["name"])
    assert cand.category == "food"
    assert cand.meal_slot == "any"


def _plan_with_legs():
    return ItineraryPlan(
        itinerary_id="t",
        cities=["北京", "上海"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    TransferItem(
                        item_id="xfer-d2",
                        day=1,
                        seq=0,
                        from_city="北京",
                        to_city="上海",
                        mode="train",
                        start_time=time(8, 30),
                        end_time=time(10, 30),
                        duration_minutes=120,
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_structural_leg_gets_real_train_number():
    plan = _plan_with_legs()
    notes = await fill_structural_leg_numbers(
        plan, start_date="2026-11-24", trains=_FakeTrain(), flights=None
    )
    leg = plan.days[0].items[0]
    assert leg.train_no == "G9"
    assert leg.flight_no is None
    assert leg.start_time == time(9, 0)
    assert leg.end_time == time(14, 0)
    assert any("G9" in n for n in notes)


@pytest.mark.asyncio
async def test_user_filled_number_never_overwritten():
    plan = _plan_with_legs()
    plan.days[0].items[0].train_no = "G1"
    await fill_structural_leg_numbers(
        plan, start_date="2026-11-24", trains=_FakeTrain(), flights=None
    )
    assert plan.days[0].items[0].train_no == "G1"


@pytest.mark.asyncio
async def test_measured_leg_enrich_opt_in_default_off(monkeypatch):
    """默认关 → 生成期零外呼，读侧 refresh_legs 仍兜（现状不变）。"""
    from app.config import get_settings
    from app.services.trip_solver.leg_numbers import enrich_measured_legs_if_enabled

    class _Agent:
        class _Amap:
            walking_route = None

        _amap = _Amap()

        async def _enrich_legs(self, plan):
            raise AssertionError("must not call when flag off")

    settings = get_settings()
    monkeypatch.setattr(
        settings, "plan_measured_legs_at_generation_enabled", False, raising=False
    )
    await enrich_measured_legs_if_enabled(_Agent(), _plan_with_legs())


@pytest.mark.asyncio
async def test_measured_leg_enrich_opt_in_on_calls_bounded(monkeypatch):
    from app.config import get_settings
    from app.services.trip_solver.leg_numbers import enrich_measured_legs_if_enabled

    calls = []

    class _Agent:
        class _Amap:
            pass

        _amap = _Amap()

        async def _enrich_legs(self, plan):
            calls.append(plan)

    settings = get_settings()
    monkeypatch.setattr(
        settings, "plan_measured_legs_at_generation_enabled", True, raising=False
    )
    plan = _plan_with_legs()
    await enrich_measured_legs_if_enabled(_Agent(), plan)
    assert calls == [plan]
