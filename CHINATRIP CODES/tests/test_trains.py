"""Tests for the TrainService abstraction + mock static timetable."""

import asyncio
from datetime import time

from app.services.itinerary.models import TransferItem
from app.services.trains import (
    MockTrainService,
    TrainOption,
    build_transfer_item,
    pick_best_train,
)

DATE = "2026-11-03"
SERVICE = MockTrainService()

ALL_PAIRS = [
    ("北京", "上海"),
    ("上海", "北京"),
    ("北京", "西安"),
    ("西安", "北京"),
    ("上海", "杭州"),
    ("杭州", "上海"),
    ("成都", "重庆"),
    ("重庆", "成都"),
]


class StubTrainService:
    """Minimal TrainService for synthetic schedules (cross-midnight etc.)."""

    def __init__(self, options: list[TrainOption]):
        self._options = options

    async def search(self, from_city: str, to_city: str, date: str):
        return self._options


def minutes(t: time) -> int:
    return t.hour * 60 + t.minute


# --- Mock timetable ---


def test_mock_covers_all_pairs_with_three_trains_each():
    for from_city, to_city in ALL_PAIRS:
        options = asyncio.run(SERVICE.search(from_city, to_city, DATE))
        assert len(options) == 3, (from_city, to_city)
        for opt in options:
            assert isinstance(opt, TrainOption)
            assert opt.from_city == from_city
            assert opt.to_city == to_city
            assert opt.date == DATE
            assert opt.train_no
            assert opt.from_station
            assert opt.to_station
            assert opt.arr_time > opt.dep_time  # all mock trains are same-day
            assert opt.duration_minutes == minutes(opt.arr_time) - minutes(opt.dep_time)


def test_mock_beijing_shanghai_plausible_duration():
    options = asyncio.run(SERVICE.search("北京", "上海", DATE))
    train_nos = {opt.train_no for opt in options}
    assert train_nos == {"G1", "G3", "G5"}
    for opt in options:
        assert 4 * 60 + 30 <= opt.duration_minutes <= 6 * 60
        assert opt.from_station == "北京南"
        assert opt.to_station == "上海虹桥"
    g1 = next(opt for opt in options if opt.train_no == "G1")
    assert g1.dep_time == time(7, 0)
    assert g1.arr_time == time(11, 30)
    assert g1.duration_minutes == 270


def test_mock_reverse_direction():
    options = asyncio.run(SERVICE.search("上海", "北京", DATE))
    assert {opt.train_no for opt in options} == {"G2", "G4", "G6"}
    assert all(opt.from_station == "上海虹桥" for opt in options)
    assert all(opt.to_station == "北京南" for opt in options)
    # Short hops stay short in both directions.
    hz = asyncio.run(SERVICE.search("杭州", "上海", DATE))
    assert all(opt.duration_minutes <= 75 for opt in hz)
    cq = asyncio.run(SERVICE.search("重庆", "成都", DATE))
    assert all(80 <= opt.duration_minutes <= 130 for opt in cq)


def test_mock_uncovered_pair_returns_empty():
    assert asyncio.run(SERVICE.search("北京", "杭州", DATE)) == []
    assert asyncio.run(SERVICE.search("拉萨", "北京", DATE)) == []
    assert asyncio.run(SERVICE.search("上海", "上海", DATE)) == []


def test_mock_date_is_pure_passthrough():
    for date in ("2026-01-01", "2026-12-31", "not-even-a-date"):
        options = asyncio.run(SERVICE.search("北京", "上海", date))
        assert options and all(opt.date == date for opt in options)


# --- pick_best_train ---


def test_pick_best_no_window_takes_earliest():
    best = asyncio.run(pick_best_train(SERVICE, "北京", "上海", DATE))
    assert best is not None
    assert best.train_no == "G1"
    assert best.dep_time == time(7, 0)


def test_pick_best_window_hits_only_in_window():
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(8, 30), time(12, 0)),
        )
    )
    assert best is not None
    assert best.train_no == "G3"  # G1 07:00 before window, G5 14:00 after


def test_pick_best_window_prefers_closest_to_window_start():
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(6, 0), time(15, 0)),
        )
    )
    assert best is not None
    assert best.train_no == "G1"  # earliest of G1/G3/G5 = closest to 06:00


def test_pick_best_window_without_trains_returns_none():
    # Last Beijing→Shanghai departure is 14:00; evening window is empty.
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(19, 30), time(20, 30)),
        )
    )
    assert best is None


def test_pick_best_uncovered_pair_returns_none():
    assert asyncio.run(pick_best_train(SERVICE, "北京", "杭州", DATE)) is None


def test_pick_best_window_boundaries_are_inclusive():
    best = asyncio.run(
        pick_best_train(
            SERVICE,
            "北京",
            "上海",
            DATE,
            preferred_window=(time(7, 0), time(7, 0)),
        )
    )
    assert best is not None
    assert best.train_no == "G1"


# --- build_transfer_item ---


def test_build_transfer_item_fills_fields():
    item = asyncio.run(
        build_transfer_item(
            SERVICE,
            from_city="北京",
            to_city="上海",
            date=DATE,
            day=3,
            seq=1,
            item_id="t-day3-1",
        )
    )
    assert isinstance(item, TransferItem)
    assert item.item_id == "t-day3-1"
    assert item.day == 3
    assert item.seq == 1
    assert item.from_city == "北京"
    assert item.to_city == "上海"
    assert item.mode == "train"
    assert item.start_time == time(7, 0)
    assert item.end_time == time(11, 30)
    assert item.duration_minutes == 270
    assert item.train_no == "G1"


def test_build_transfer_item_respects_window():
    item = asyncio.run(
        build_transfer_item(
            SERVICE,
            from_city="北京",
            to_city="上海",
            date=DATE,
            day=2,
            seq=2,
            item_id="t-day2-2",
            preferred_window=(time(8, 30), time(12, 0)),
        )
    )
    assert item is not None
    assert item.train_no == "G3"
    assert item.start_time == time(9, 0)


def test_build_transfer_item_no_train_returns_none():
    # Uncovered pair and empty window both degrade to None.
    assert (
        asyncio.run(
            build_transfer_item(
                SERVICE,
                from_city="北京",
                to_city="杭州",
                date=DATE,
                day=1,
                seq=1,
                item_id="t-none-1",
            )
        )
        is None
    )
    assert (
        asyncio.run(
            build_transfer_item(
                SERVICE,
                from_city="北京",
                to_city="上海",
                date=DATE,
                day=1,
                seq=1,
                item_id="t-none-2",
                preferred_window=(time(19, 30), time(20, 30)),
            )
        )
        is None
    )


def test_build_transfer_item_cross_midnight_truncates_end_time():
    overnight = TrainOption(
        train_no="D311",
        dep_time=time(22, 15),
        arr_time=time(6, 40),  # next day: arr < dep
        duration_minutes=505,
        from_station="北京南",
        to_station="上海虹桥",
        from_city="北京",
        to_city="上海",
        date=DATE,
    )
    item = asyncio.run(
        build_transfer_item(
            StubTrainService([overnight]),
            from_city="北京",
            to_city="上海",
            date=DATE,
            day=1,
            seq=1,
            item_id="t-overnight",
        )
    )
    assert item is not None
    assert item.start_time == time(22, 15)
    assert item.end_time == time(23, 59)  # day-boundary approximation
    assert item.duration_minutes == 505  # true duration is kept
    assert item.train_no == "D311"
