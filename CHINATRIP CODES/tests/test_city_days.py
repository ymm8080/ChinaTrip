"""Per-city day allocation (H5 form: origin + via×3 + end, each with days).

Product rules 2026-10-19: the origin city is departure-only (no activity
days, outbound transfer on day 1); the last day = activities in the final
destination + the return leg home. ``city_days`` (destination → stay days)
drives each destination's window; the H5 sends days = sum of stays.
"""

import asyncio
import json
from datetime import time

from app.services.agent.plan import PlanningAgent, _city_day_ranges
from app.services.itinerary import TransferItem, VisitItem
from app.services.llm.base import ChatResult
from app.services.trains import TrainOption


class ScriptedLLM:
    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        assert self.replies, "scripted replies exhausted"
        return ChatResult(content=self.replies.pop(0), model="scripted")


class NoTrains:
    """No schedule data at all → transfers fall back to placeholders."""

    async def search(self, *args, **kwargs):
        return []


def _train(no, dep, arr, from_city, to_city):
    dep_t, arr_t = time(*dep), time(*arr)
    return TrainOption(
        train_no=no,
        dep_time=dep_t,
        arr_time=arr_t,
        duration_minutes=(arr_t.hour * 60 + arr_t.minute)
        - (dep_t.hour * 60 + dep_t.minute),
        from_station=from_city + "站",
        to_station=to_city + "站",
        from_city=from_city,
        to_city=to_city,
        date="",
    )


class StubTrains:
    """Every pair gets a morning and an evening train."""

    async def search(self, from_city, to_city, date=""):
        return [
            _train("G1", (8, 0), (11, 0), from_city, to_city),
            _train("G9", (18, 30), (21, 30), from_city, to_city),
        ]


def v0_reply(items: list[dict]) -> str:
    return json.dumps({"items": items, "assumptions": []}, ensure_ascii=False)


def visits_of(session):
    return [i for d in session.plan.days for i in d.items if isinstance(i, VisitItem)]


def transfers_of(session):
    return [
        i for d in session.plan.days for i in d.items if isinstance(i, TransferItem)
    ]


def test_city_day_ranges_split():
    # no city_days: every non-last destination gets one day (legacy split)
    assert _city_day_ranges(["上海", "杭州", "苏州"], 4) == {
        "杭州": (1, 1),
        "苏州": (2, 4),
    }
    # 杭州 stays 2 → 杭州 [1,2], 苏州 [3,5]
    assert _city_day_ranges(["上海", "杭州", "苏州"], 5, {"杭州": 2}) == {
        "杭州": (1, 2),
        "苏州": (3, 5),
    }
    # single city: unchanged, full span
    assert _city_day_ranges(["北京"], 3) == {"北京": (1, 3)}
    # stay longer than the trip: keep >=1 day per destination, monotonic
    assert _city_day_ranges(["上海", "杭州", "苏州"], 3, {"杭州": 5}) == {
        "杭州": (1, 2),
        "苏州": (3, 3),
    }


def test_v0_city_days_windows_transfers_and_return_leg():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "西湖",
                        "city": "杭州",
                        "category": "sight",
                        "day": 1,
                        "duration_minutes": 90,
                    },
                    {
                        "name": "拙政园",
                        "city": "苏州",
                        "category": "sight",
                        "day": 3,
                        "duration_minutes": 90,
                    },
                    {
                        "name": "平江路",
                        "city": "苏州",
                        "category": "sight",
                        "day": 5,
                        "duration_minutes": 60,
                    },
                ]
            )
        ]
    )
    agent = PlanningAgent(llm, train_service=NoTrains())
    session = asyncio.run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州", "苏州"],
            days=5,
            preferences="园林",
            city_days={"杭州": 2, "苏州": 3},
        )
    )
    assert session.state == "ready"
    by_city: dict[str, list[int]] = {}
    for v in visits_of(session):
        by_city.setdefault(v.city, []).append(v.day)
    assert all(1 <= d <= 2 for d in by_city["杭州"])
    assert all(3 <= d <= 5 for d in by_city["苏州"])
    # 起点城市不安排活动
    assert not any(v.city == "上海" for v in visits_of(session))
    # 出发段第1天、跨城段跟随窗口、返程段最后一天
    legs = [(t.from_city, t.to_city, t.day) for t in transfers_of(session)]
    assert legs == [("上海", "杭州", 1), ("杭州", "苏州", 3), ("苏州", "上海", 5)]
    # 最后一天：有活动 + 傍晚返程（白天留给活动）
    last = session.plan.days[-1]
    assert any(isinstance(i, VisitItem) for i in last.items)
    ret = next(i for i in last.items if isinstance(i, TransferItem))
    assert ret.start_time.hour == 17


def test_return_leg_prefers_evening_train_and_keeps_last_day_visits():
    llm = ScriptedLLM(
        [
            v0_reply(
                [
                    {
                        "name": "西湖",
                        "city": "杭州",
                        "category": "sight",
                        "day": 1,
                        "duration_minutes": 90,
                    },
                    {
                        "name": "拙政园",
                        "city": "苏州",
                        "category": "sight",
                        "day": 5,
                        "duration_minutes": 90,
                    },
                ]
            )
        ]
    )
    agent = PlanningAgent(llm, train_service=StubTrains())
    session = asyncio.run(
        agent.start(
            device_id="d1",
            cities=["上海", "杭州", "苏州"],
            days=5,
            preferences="园林",
            city_days={"杭州": 2, "苏州": 3},
        )
    )
    assert session.state == "ready"
    last = session.plan.days[-1]
    # 末日活动未被返程班次挤掉
    assert any(isinstance(i, VisitItem) for i in last.items)
    # 返程选 (15:00, 21:00) 窗口内最早班（18:30 晚班车），而不是 8:00 早班车
    ret = next(i for i in last.items if isinstance(i, TransferItem))
    assert ret.from_city == "苏州" and ret.to_city == "上海"
    assert ret.start_time == time(18, 30)
