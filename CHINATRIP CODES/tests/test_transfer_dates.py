"""票务真实日期与日期落定即预热（2026-10-28 用户拍板：开始日期+城市齐，
火车查询就开跑；转场腿用真实乘车日查 12306，不再恒 today+3 占位）。"""

from __future__ import annotations

import asyncio

from app.services.agent.plan import PlanningAgent, _leg_date_iso
from app.services.trains import MockTrainService


class _NoLLM:
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("ticket paths must not call the LLM")


class RecordingTrains(MockTrainService):
    def __init__(self):
        super().__init__()
        self.queries: list[tuple[str, str, str]] = []

    async def search(self, from_city, to_city, date):
        self.queries.append((from_city, to_city, date))
        return await super().search(from_city, to_city, date)


def _agent(trains: RecordingTrains) -> PlanningAgent:
    return PlanningAgent(_NoLLM(), train_service=trains)


def test_leg_date_iso_math():
    assert _leg_date_iso(None, 3) == ""
    assert _leg_date_iso("", 1) == ""
    assert _leg_date_iso("2026-11-10", 1) == "2026-11-10"
    assert _leg_date_iso("2026-11-10", 3) == "2026-11-12"
    assert _leg_date_iso("2026-11-30", 2) == "2026-12-01"  # 跨月
    assert _leg_date_iso("not-a-date", 2) == ""
    assert _leg_date_iso("2026-11-10T08:00:00", 2) == "2026-11-11"  # ISO 时刻截日期


def test_build_transfers_queries_real_travel_dates():
    trains = RecordingTrains()
    agent = _agent(trains)
    asyncio.run(
        agent._build_transfers(["上海", "成都"], 2, {}, start_date="2026-11-10")
    )
    pairs = {(f, t): d for f, t, d in trains.queries}
    assert pairs.get(("上海", "成都")) == "2026-11-10"  # day1 去程
    assert pairs.get(("成都", "上海")) == "2026-11-11"  # day2 返程


def test_build_transfers_blank_start_date_keeps_placeholder():
    trains = RecordingTrains()
    agent = _agent(trains)
    asyncio.run(agent._build_transfers(["上海", "成都"], 2, {}, start_date=None))
    assert all(d == "" for _, _, d in trains.queries)


def test_prefetch_transfer_schedules_covers_all_legs():
    trains = RecordingTrains()
    agent = _agent(trains)
    asyncio.run(
        agent.prefetch_transfer_schedules(["上海", "成都", "重庆"], 6, "2026-11-10")
    )
    pairs = {(f, t) for f, t, _d in trains.queries}
    assert pairs == {("上海", "成都"), ("成都", "重庆"), ("重庆", "上海")}
    dates = {d for _f, _t, d in trains.queries}
    assert "2026-11-10" in dates  # day1 去程
    assert "2026-11-15" in dates  # day6 返程
    assert all(d.startswith("2026-11-") for d in dates)


def test_prefetch_noop_without_date_or_single_city():
    trains = RecordingTrains()
    agent = _agent(trains)
    asyncio.run(agent.prefetch_transfer_schedules(["上海", "成都"], 2, None))
    asyncio.run(agent.prefetch_transfer_schedules(["上海"], 2, "2026-11-10"))
    assert trains.queries == []


def test_start_schedules_prefetch_when_date_and_cities_known():
    trains = RecordingTrains()
    agent = _agent(trains)

    async def scenario():
        session = await agent.start(
            device_id="d1",
            cities=["上海", "成都"],
            days=2,
            preferences="博物馆",
            start_date="2026-11-10",
        )
        task = getattr(agent, "_transfer_prefetch_task", None)
        assert task is not None
        await asyncio.wait_for(task, 5)
        assert ("上海", "成都", "2026-11-10") in trains.queries
        return session

    session = asyncio.run(scenario())
    assert session.start_date == "2026-11-10"
