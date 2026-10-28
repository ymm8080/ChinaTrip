"""航班与火车同构（2026-10-28 用户拍板）：FlightService 协议 + mock 语义
（9:00/17:00/180min 与旧占位逐位一致）+ 真实乘车日贯通 + 预热覆盖航班腿。"""

from __future__ import annotations

import asyncio
from datetime import time

from app.services.agent.plan import PlanningAgent
from app.services.flights import (
    FlightOption,
    FlightService,
    MockFlightService,
    pick_best_flight,
)
from app.services.itinerary import GeoPoint
from app.services.trains import MockTrainService


class _NoLLM:
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("transfer paths must not call the LLM")


class RecordingFlights(MockFlightService):
    def __init__(self):
        super().__init__()
        self.queries: list[tuple[str, str, str]] = []

    async def search(self, from_city, to_city, date):
        self.queries.append((from_city, to_city, date))
        return await super().search(from_city, to_city, date)


class EmptyTrains(MockTrainService):
    """任何城市对都无火车 → 全部落到降级路径。"""

    async def search(self, from_city, to_city, date):
        return []


def test_mock_table_and_pick_best_flight_semantics():
    mock = MockFlightService()

    async def scenario():
        no_window = await pick_best_flight(mock, "上海", "三亚", "2026-11-10")
        evening = await pick_best_flight(
            mock,
            "三亚",
            "上海",
            "2026-11-12",
            preferred_window=(time(15, 0), time(21, 0)),
        )
        midday = await pick_best_flight(
            mock,
            "上海",
            "三亚",
            "2026-11-10",
            preferred_window=(time(10, 0), time(14, 0)),
        )
        same_city = await pick_best_flight(mock, "上海", "上海", "2026-11-10")
        return no_window, evening, midday, same_city

    no_window, evening, midday, same_city = asyncio.run(scenario())
    assert no_window is not None and no_window.dep_time == time(9, 0)
    assert no_window.duration_minutes == 180
    assert evening is not None and evening.dep_time == time(17, 0)  # 窗内最早
    assert midday is None  # 窗内无班 → None（调用方回退，不用窗外班顶替）
    assert same_city is None  # 同城无班 → pick 返回 None


def test_build_transfers_flight_uses_service_times_and_real_dates():
    flights = RecordingFlights()
    agent = PlanningAgent(_NoLLM(), train_service=EmptyTrains(), flight_service=flights)
    anchors = {
        "上海": GeoPoint(lon=121.47, lat=31.23),
        "三亚": GeoPoint(lon=109.50, lat=18.25),
    }
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(["上海", "三亚"], 2, anchors, start_date="2026-11-10")
    )
    by_day = {t.day: t for t in transfers}
    assert by_day[1].mode == "flight" and by_day[1].start_time == time(9, 0)
    assert by_day[1].duration_minutes == 180
    assert by_day[2].mode == "flight" and by_day[2].start_time == time(17, 0)
    # 航班查询拿到真实乘车日（去程 D1、返程 D2）
    assert ("上海", "三亚", "2026-11-10") in flights.queries
    assert ("三亚", "上海", "2026-11-11") in flights.queries


def test_prefetch_warms_flight_legs_too():
    flights = RecordingFlights()
    agent = PlanningAgent(_NoLLM(), train_service=EmptyTrains(), flight_service=flights)
    asyncio.run(agent.prefetch_transfer_schedules(["上海", "成都"], 2, "2026-11-10"))
    assert {q[:2] for q in flights.queries} == {("上海", "成都"), ("成都", "上海")}
    assert all(q[2].startswith("2026-11-") for q in flights.queries)


def test_flight_service_protocol_shape():
    class OneFlight(FlightService):
        async def search(self, from_city, to_city, date):
            return [FlightOption("CA1234", time(11, 30), time(14, 40), 190)]

    async def scenario():
        return await pick_best_flight(OneFlight(), "北京", "三亚", "2026-11-10")

    best = asyncio.run(scenario())
    assert best.flight_no == "CA1234" and best.dep_time == time(11, 30)
