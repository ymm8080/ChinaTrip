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
        agent._build_transfers(
            ["上海", "三亚", "上海"], 2, anchors, start_date="2026-11-10"
        )
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
    """距离未知（无锚点）保留 11-04 旧口径：去程/回程优先飞机，中途城际
    腿仍以火车为先。有锚点时以 2026-11-06 距离闸为准（见上方距离测试）。"""
    agent = PlanningAgent(_NoLLM(), train_service=MockTrainService())
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(
            ["上海", "北京", "西安", "上海"], 3, {}, start_date="2026-11-10"
        )
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
        agent._build_transfers(["上海", "杭州", "上海"], 2, {}, start_date="2026-11-10")
    )
    out, ret = transfers
    # 08:00 闸（2026-11-03 拍板「火车 start time start from 8AM」）：
    # G7351 07:15 出局，G7503 12:10 当选。
    assert out.mode == "train" and out.train_no == "G7503"
    assert ret.mode == "train" and ret.start_time == time(20, 0)  # 晚间窗 G7360
    assert any("去程 上海→杭州" in a and "无航班" in a for a in assumptions)
    assert any("返程 杭州→上海" in a and "无航班" in a for a in assumptions)


def test_distance_gate_flight_over_600km_train_under():
    """2026-11-06 用户拍板：直线 >600km 选航班、≤600km 选火车。

    西安→杭州 ~1130km 必须飞机（11-04 案曾排成火车）；杭州→上海
    ~165km 必须火车（11-04 案曾排成飞机）。返程 上海→西安 同样 >600km
    走航班晚间窗。"""
    agent = PlanningAgent(_NoLLM(), train_service=MockTrainService())
    anchors = {
        "西安": GeoPoint(lon=108.94, lat=34.34),
        "杭州": GeoPoint(lon=120.16, lat=30.29),
        "上海": GeoPoint(lon=121.47, lat=31.23),
    }
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(
            ["西安", "杭州", "上海", "西安"], 3, anchors, start_date="2026-11-10"
        )
    )
    out, hop, ret = transfers
    assert (out.from_city, out.to_city) == ("西安", "杭州")
    assert out.mode == "flight" and out.flight_no == "MU1001"
    assert (hop.from_city, hop.to_city) == ("杭州", "上海")
    assert hop.mode == "train" and hop.train_no
    assert (ret.from_city, ret.to_city) == ("上海", "西安")
    assert ret.mode == "flight" and ret.start_time == time(17, 0)


def test_intercity_mode_train_overrides_distance_gate():
    """2026-11-07 拍板：起始页指定「🚄 火车」覆盖距离闸——>600km 对
    （北京→西安 ~900km）也只查火车，且全程不碰航班源。返程窗（15-21时）
    命中 G412 16:30。"""
    flights = RecordingFlights()
    agent = PlanningAgent(
        _NoLLM(), train_service=MockTrainService(), flight_service=flights
    )
    anchors = {
        "北京": GeoPoint(lon=116.40, lat=39.90),
        "西安": GeoPoint(lon=108.94, lat=34.34),
    }
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(
            ["北京", "西安", "北京"],
            2,
            anchors,
            start_date="2026-11-10",
            intercity_mode="train",
        )
    )
    out, ret = transfers
    assert out.mode == "train" and out.train_no
    assert ret.mode == "train" and ret.start_time == time(16, 30)
    assert flights.queries == []


def test_intercity_mode_flight_overrides_distance_gate():
    """2026-11-07 拍板：起始页指定「✈️ 飞机」覆盖距离闸——≤600km 对
    （上海→杭州 ~165km）也先查航班并当选（去程 9:00 / 返程窗内 17:00）。"""
    flights = RecordingFlights()
    agent = PlanningAgent(
        _NoLLM(), train_service=MockTrainService(), flight_service=flights
    )
    anchors = {
        "上海": GeoPoint(lon=121.47, lat=31.23),
        "杭州": GeoPoint(lon=120.16, lat=30.29),
    }
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(
            ["上海", "杭州", "上海"],
            2,
            anchors,
            start_date="2026-11-10",
            intercity_mode="flight",
        )
    )
    out, ret = transfers
    assert out.mode == "flight" and out.flight_no == "MU1001"
    assert ret.mode == "flight" and ret.start_time == time(17, 0)
    assert flights.queries  # 指定飞机确实查了航班源


def test_intercity_mode_flight_falls_back_to_train_with_assumption():
    """指定飞机但航班源无班 → 落回火车并留痕（既有降级链不动）。"""
    agent = PlanningAgent(
        _NoLLM(), train_service=MockTrainService(), flight_service=EmptyFlights()
    )
    anchors = {
        "上海": GeoPoint(lon=121.47, lat=31.23),
        "杭州": GeoPoint(lon=120.16, lat=30.29),
    }
    transfers, assumptions = asyncio.run(
        agent._build_transfers(
            ["上海", "杭州", "上海"],
            2,
            anchors,
            start_date="2026-11-10",
            intercity_mode="flight",
        )
    )
    out, ret = transfers
    assert out.mode == "train" and out.train_no == "G7503"
    assert ret.mode == "train"
    assert any("上海→杭州" in a and "无航班" in a for a in assumptions)


class _LibTop:
    """poi_details 桩：只实现锚点读取路径。"""

    def __init__(self, rows):
        self.rows = rows

    def top_pois_in_city(self, city, depth):
        return self.rows


def test_ensure_origin_anchor_fills_origin_and_gate_works():
    """2026-11-07 沪杭返程实弹根修：候选搜索跳过出发城（2026-10-30
    配额优化，检索循环 cities[1:]）→ anchors 恒缺 origin → 11-06 距离闸
    对去程/返程 dist 恒 None，静默回落 11-04「航班优先」（杭州→上海
    165km 被排成航班）。库 top-1 补锚后返程必须火车。"""
    agent = PlanningAgent(
        _NoLLM(),
        train_service=MockTrainService(),
        poi_details=_LibTop(
            [
                {
                    "name": "外滩",
                    "city": "上海",
                    "location": {"lon": 121.49, "lat": 31.24},
                }
            ]
        ),
    )
    anchors = {"杭州": GeoPoint(lon=120.16, lat=30.29)}
    asyncio.run(agent._ensure_origin_anchor(anchors, ["上海", "杭州"]))
    assert anchors["上海"] == GeoPoint(lon=121.49, lat=31.24)
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(
            ["上海", "杭州", "上海"], 2, anchors, start_date="2026-11-10"
        )
    )
    out, ret = transfers
    assert out.mode == "train" and out.train_no
    assert ret.mode == "train"


def test_ensure_origin_anchor_accepts_library_tuple_location():
    """库真实形状回归锚（2026-11-08 活服复现）：top_pois_in_city 出库
    location 为 (lon, lat) 元组——11-07 根修的桩只喂 dict 形状，元组行
    全跳过 → 出发城锚恒缺 → 距离闸盲（上海→杭州 165km 排成航班）。
    元组行必须能补锚，沪杭往返必须火车。"""
    agent = PlanningAgent(
        _NoLLM(),
        train_service=MockTrainService(),
        poi_details=_LibTop(
            [{"name": "东方明珠", "city": "上海", "location": (121.50, 31.24)}]
        ),
    )
    anchors = {"杭州": GeoPoint(lon=120.16, lat=30.29)}
    asyncio.run(agent._ensure_origin_anchor(anchors, ["上海", "杭州"]))
    assert anchors["上海"] == GeoPoint(lon=121.50, lat=31.24)
    transfers, _assumptions = asyncio.run(
        agent._build_transfers(
            ["上海", "杭州", "上海"], 2, anchors, start_date="2026-11-10"
        )
    )
    out, ret = transfers
    assert out.mode == "train" and out.train_no
    assert ret.mode == "train"


def test_ensure_origin_anchor_noop_when_present_or_library_empty():
    agent = PlanningAgent(_NoLLM(), train_service=MockTrainService())
    anchors = {"上海": GeoPoint(lon=121.47, lat=31.23)}
    asyncio.run(agent._ensure_origin_anchor(anchors, ["上海", "杭州"]))
    assert anchors == {"上海": GeoPoint(lon=121.47, lat=31.23)}  # 已有→不动
    empty = PlanningAgent(
        _NoLLM(), train_service=MockTrainService(), poi_details=_LibTop([])
    )
    anchors2: dict = {}
    asyncio.run(empty._ensure_origin_anchor(anchors2, ["上海", "杭州"]))
    assert anchors2 == {}  # 库空→保持旧行为（盲区留日志），不炸不编造


def test_prefetch_warms_flight_legs_too():
    flights = RecordingFlights()
    agent = PlanningAgent(_NoLLM(), train_service=EmptyTrains(), flight_service=flights)
    asyncio.run(
        agent.prefetch_transfer_schedules(["上海", "成都", "上海"], 2, "2026-11-10")
    )
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
