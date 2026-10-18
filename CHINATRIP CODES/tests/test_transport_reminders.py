"""Tests for departure reminders + missed-connection fallback (§6.13).

All datetimes are hand-built and every ``now`` is passed explicitly — no
wall-clock reads. Train fallback uses the real MockTrainService, whose
timetable is deterministic (北京→上海: G1 07:00 / G3 09:00 / G5 14:00,
成都→重庆: G8501 07:30 / G8511 12:20 / G8521 17:40, table-wide last
departure 20:05 G8522).
"""

import asyncio
from datetime import datetime, time

import pytest

from app.services.trains import MockTrainService
from app.services.transport_reminders import (
    FLIGHT_LEAVE_BUFFER_MINUTES,
    TRAIN_LEAVE_BUFFER_MINUTES,
    build_departure_reminders,
    missed_connection_fallback,
)

STATION_LOCATION = {"lon": 116.3, "lat": 39.9}


def _taxi_stub(station_name, lon, lat):
    return {"stub": True, "station": station_name, "lon": lon, "lat": lat}


# --- build_departure_reminders ---


def test_train_reminders_three_tiers_sorted_offsets():
    leg = {
        "type": "train",
        "departure_time": datetime(2026, 11, 3, 12, 0),
        "station_name": "北京南",
        "station_location": STATION_LOCATION,
    }
    reminders = build_departure_reminders(leg)  # now=None → no filtering
    assert [r["kind"] for r in reminders] == ["heads_up", "prepare", "leave_now"]
    # ascending by at
    assert [r["at"] for r in reminders] == sorted(r["at"] for r in reminders)
    assert reminders[0]["at"] == datetime(2026, 11, 2, 12, 0)  # -24h
    assert reminders[1]["at"] == datetime(2026, 11, 3, 10, 0)  # -2h
    assert reminders[2]["at"] == datetime(2026, 11, 3, 11, 15)  # -45min
    assert reminders[0]["message"] == "明天从北京南出发"
    assert reminders[1]["message"] == "2小时后从北京南出发"
    assert reminders[2]["message"] == "现在出发去北京南（预留45分钟缓冲）"
    assert TRAIN_LEAVE_BUFFER_MINUTES == 45


def test_flight_reminders_use_90_minutes():
    leg = {
        "type": "flight",
        "departure_time": datetime(2026, 11, 5, 15, 0),
        "station_name": "首都机场T3",
        "station_location": STATION_LOCATION,
    }
    reminders = build_departure_reminders(leg)
    assert [r["kind"] for r in reminders] == ["heads_up", "prepare", "leave_now"]
    assert reminders[2]["at"] == datetime(2026, 11, 5, 13, 30)  # -90min
    assert "90分钟缓冲" in reminders[2]["message"]
    assert FLIGHT_LEAVE_BUFFER_MINUTES == 90


def test_now_filter_drops_past_tiers_keeps_future():
    leg = {
        "type": "train",
        "departure_time": datetime(2026, 11, 3, 12, 0),
        "station_name": "北京南",
        "station_location": STATION_LOCATION,
    }
    # heads_up 11-02 12:00 and prepare 11-03 10:00 are past; only leave_now.
    partial = build_departure_reminders(leg, now=datetime(2026, 11, 3, 10, 30))
    assert [r["kind"] for r in partial] == ["leave_now"]
    # all three tiers still in the future → all kept.
    full = build_departure_reminders(leg, now=datetime(2026, 11, 1, 0, 0))
    assert [r["kind"] for r in full] == ["heads_up", "prepare", "leave_now"]


def test_invalid_leg_type_raises():
    leg = {
        "type": "bus",
        "departure_time": datetime(2026, 11, 3, 12, 0),
        "station_name": "北京南",
    }
    with pytest.raises(ValueError):
        build_departure_reminders(leg)
    with pytest.raises(ValueError):  # type missing entirely
        build_departure_reminders(
            {
                "departure_time": datetime(2026, 11, 3),
            }
        )


def test_missing_departure_time_raises():
    leg = {"type": "train", "station_name": "北京南"}
    with pytest.raises(ValueError):
        build_departure_reminders(leg)


# --- missed_connection_fallback ---


def _train_leg(**overrides):
    leg = {
        "type": "train",
        "departure_time": datetime(2026, 11, 3, 7, 0),  # missed G1 07:00
        "station_name": "北京南",
        "station_location": STATION_LOCATION,
        "from_city": "北京",
        "to_city": "上海",
    }
    leg.update(overrides)
    return leg


def test_missed_train_next_departures_sorted_with_taxi_stub():
    result = asyncio.run(
        missed_connection_fallback(
            _train_leg(),
            train_service=MockTrainService(),
            taxi_deeplink_builder=_taxi_stub,
            now=datetime(2026, 11, 3, 7, 30),
        )
    )
    assert result["leg_type"] == "train"
    departures = result["next_departures"]
    assert [d["train_no"] for d in departures] == ["G3", "G5"]
    assert [d["dep_time"] for d in departures] == [time(9, 0), time(14, 0)]
    assert departures == sorted(departures, key=lambda d: d["dep_time"])
    assert all(d["from_station"] == "北京南" for d in departures)  # pass-through
    assert result["taxi"] == {
        "stub": True,
        "station": "北京南",
        "lon": STATION_LOCATION["lon"],
        "lat": STATION_LOCATION["lat"],
    }
    assert result["note"]


def test_missed_train_caps_at_three_departures():
    result = asyncio.run(
        missed_connection_fallback(
            _train_leg(
                departure_time=datetime(2026, 11, 3, 7, 30),
                station_name="成都东",
                from_city="成都",
                to_city="重庆",
            ),
            train_service=MockTrainService(),
            taxi_deeplink_builder=_taxi_stub,
            now=datetime(2026, 11, 3, 7, 0),
        )
    )
    departures = result["next_departures"]
    assert len(departures) == 3
    assert [d["train_no"] for d in departures] == ["G8501", "G8511", "G8521"]


def test_missed_train_after_last_departure_returns_empty():
    # 21:00 is past the whole mock timetable's last departure (20:05).
    result = asyncio.run(
        missed_connection_fallback(
            _train_leg(),
            train_service=MockTrainService(),
            taxi_deeplink_builder=_taxi_stub,
            now=datetime(2026, 11, 3, 21, 0),
        )
    )
    assert result["next_departures"] == []
    assert result["leg_type"] == "train"


def test_flight_fallback_has_no_departures():
    leg = {
        "type": "flight",
        "departure_time": datetime(2026, 11, 3, 9, 0),
        "station_name": "首都机场T3",
        "station_location": STATION_LOCATION,
    }
    result = asyncio.run(
        missed_connection_fallback(
            leg,
            train_service=MockTrainService(),
            taxi_deeplink_builder=_taxi_stub,
            now=datetime(2026, 11, 3, 9, 30),
        )
    )
    assert result["leg_type"] == "flight"
    assert result["next_departures"] == []  # never fabricate flights
    assert "无航班" in result["note"]
    assert result["taxi"] == {  # taxi to the airport still provided
        "stub": True,
        "station": "首都机场T3",
        "lon": STATION_LOCATION["lon"],
        "lat": STATION_LOCATION["lat"],
    }


def test_fallback_without_station_location_taxi_is_none():
    result = asyncio.run(
        missed_connection_fallback(
            _train_leg(station_location=None),
            train_service=MockTrainService(),
            taxi_deeplink_builder=_taxi_stub,
            now=datetime(2026, 11, 3, 7, 30),
        )
    )
    assert result["taxi"] is None
    assert result["next_departures"]  # departures unaffected
