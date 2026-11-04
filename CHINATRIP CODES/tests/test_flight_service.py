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


class EmptyFlights(MockFlightService):
    """任何城市对都无航班 → 去程/回程退回火车或占位。"""

    async def search(self, from_city, to_city, date):
        return []


def test_outbound_and_return_prefer_flight_middle_hop_stays_train():
    """2026-11-04 用户拍板：去程/回程优先飞机，中途城际腿仍以火车为先。"""
    agent = PlanningAgent(_NoLLM(), train_service=MockTrainService())
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(["上海", "北京", "西安"], 3, {}, start_date="2026-11-10")
    )
    out, hop, ret = transfers
    assert (out.from_city, out.to_city) == ("上海", "北京")
    assert out.mode == "flight" and out.flight_no == "MU1001"
    # 北京→西安是中转腿：火车仍优先（G87 07:00 被 08:00 闸拦，G25 10:00 当选）
    assert (hop.from_city, hop.to_city) == ("北京", "西安")
    assert hop.mode == "train" and hop.train_no == "G25"
    # 返程腿走晚间窗（15:00-21:00）的 17:00 航班
    assert (ret.from_city, ret.to_city) == ("西安", "上海")
    assert ret.mode == "flight" and ret.start_time == time(17, 0)


def test_outbound_return_fall_back_to_train_with_assumption():
    """航班源当日无班 → 去程/回程退回火车，并把降级写进 assumptions。"""
    agent = PlanningAgent(
        _NoLLM(), train_service=MockTrainService(), flight_service=EmptyFlights()
    )
    transfers, assumptions = asyncio.run(
        agent._build_transfers(["上海", "杭州"], 2, {}, start_date="2026-11-10")
    )
    out, ret = transfers
    # 08:00 闸（2026-11-03 拍板「火车 start time start from 8AM」）：
    # G7351 07:15 出局，G7503 12:10 当选。
    assert out.mode == "train" and out.train_no == "G7503"
    assert ret.mode == "train" and ret.start_time == time(20, 0)  # 晚间窗 G7360
    assert any("去程 上海→杭州" in a and "无航班" in a for a in assumptions)
    assert any("返程 杭州→上海" in a and "无航班" in a for a in assumptions)


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
