"""Train schedule static-library abstraction (design v2.0 §6.2 v1.9.9 / §8).

Cross-city tooling (mounted W3-4 with multi-city planning): the planner only
needs read-only timetable lookups. The real backend is the 12306 static
schedule library — a weekly-refresh data source — whose concrete
implementation will replace :class:`MockTrainService` behind the same
:class:`TrainService` protocol.

Purchase is a handoff (iron rule 22): booking happens via the official 12306
App deeplink in the action-orchestration layer, never here. This module is
read-only — no bookings, no funds, no credentials.
"""

from datetime import time
from typing import NamedTuple, Protocol

from pydantic import BaseModel

from app.services.itinerary.models import TransferItem


class TrainOption(BaseModel):
    """One schedule entry from the static timetable library."""

    train_no: str
    dep_time: time
    arr_time: time
    duration_minutes: int
    from_station: str
    to_station: str
    from_city: str
    to_city: str
    date: str  # ISO date, pass-through from the caller


class TrainService(Protocol):
    async def search(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]: ...


# --- deterministic mock timetable (stands in for the weekly 12306 snapshot) ---


class _RawTrain(NamedTuple):
    train_no: str
    dep: time
    arr: time
    from_station: str
    to_station: str


_MOCK_TIMETABLE: dict[tuple[str, str], tuple[_RawTrain, ...]] = {
    # 北京 ↔ 上海 (~4.5-6h)
    ("北京", "上海"): (
        _RawTrain("G1", time(7, 0), time(11, 30), "北京南", "上海虹桥"),
        _RawTrain("G3", time(9, 0), time(13, 36), "北京南", "上海虹桥"),
        _RawTrain("G5", time(14, 0), time(19, 24), "北京南", "上海虹桥"),
    ),
    ("上海", "北京"): (
        _RawTrain("G2", time(7, 0), time(11, 30), "上海虹桥", "北京南"),
        _RawTrain("G4", time(9, 0), time(13, 36), "上海虹桥", "北京南"),
        _RawTrain("G6", time(14, 0), time(19, 24), "上海虹桥", "北京南"),
    ),
    # 北京 ↔ 西安 (~4.5-5.5h)
    ("北京", "西安"): (
        _RawTrain("G87", time(7, 0), time(11, 25), "北京西", "西安北"),
        _RawTrain("G25", time(10, 0), time(14, 29), "北京西", "西安北"),
        _RawTrain("G411", time(15, 30), time(21, 7), "北京西", "西安北"),
    ),
    ("西安", "北京"): (
        _RawTrain("G88", time(8, 0), time(12, 24), "西安北", "北京西"),
        _RawTrain("G26", time(11, 0), time(15, 30), "西安北", "北京西"),
        _RawTrain("G412", time(16, 30), time(22, 3), "西安北", "北京西"),
    ),
    # 上海 ↔ 杭州 (~1h)
    ("上海", "杭州"): (
        _RawTrain("G7351", time(7, 15), time(8, 16), "上海虹桥", "杭州东"),
        _RawTrain("G7503", time(12, 10), time(13, 14), "上海虹桥", "杭州东"),
        _RawTrain("G7359", time(18, 30), time(19, 32), "上海虹桥", "杭州东"),
    ),
    ("杭州", "上海"): (
        _RawTrain("G7352", time(8, 40), time(9, 41), "杭州东", "上海虹桥"),
        _RawTrain("G7504", time(13, 40), time(14, 43), "杭州东", "上海虹桥"),
        _RawTrain("G7360", time(20, 0), time(21, 2), "杭州东", "上海虹桥"),
    ),
    # 成都 ↔ 重庆 (~1.5-2h)
    ("成都", "重庆"): (
        _RawTrain("G8501", time(7, 30), time(9, 12), "成都东", "重庆北"),
        _RawTrain("G8511", time(12, 20), time(14, 5), "成都东", "重庆北"),
        _RawTrain("G8521", time(17, 40), time(19, 30), "成都东", "重庆北"),
    ),
    ("重庆", "成都"): (
        _RawTrain("G8502", time(9, 35), time(11, 17), "重庆北", "成都东"),
        _RawTrain("G8512", time(14, 30), time(16, 12), "重庆北", "成都东"),
        _RawTrain("G8522", time(20, 5), time(21, 50), "重庆北", "成都东"),
    ),
}

_MOCK_COVERED_PAIRS = tuple(_MOCK_TIMETABLE.keys())


def _duration_minutes(dep: time, arr: time) -> int:
    """Minutes from dep to arr; arr earlier than dep means next-day arrival."""
    delta = (arr.hour * 60 + arr.minute) - (dep.hour * 60 + dep.minute)
    if delta < 0:
        delta += 24 * 60
    return delta


class MockTrainService(TrainService):
    """In-memory deterministic timetable; [] for uncovered city pairs.

    The date is passed through untouched: the static library refreshes
    weekly, so day-level filtering is deliberately out of scope here.
    """

    async def search(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]:
        return [
            TrainOption(
                train_no=raw.train_no,
                dep_time=raw.dep,
                arr_time=raw.arr,
                duration_minutes=_duration_minutes(raw.dep, raw.arr),
                from_station=raw.from_station,
                to_station=raw.to_station,
                from_city=from_city,
                to_city=to_city,
                date=date,
            )
            for raw in _MOCK_TIMETABLE.get((from_city, to_city), ())
        ]


async def pick_best_train(
    service: TrainService,
    from_city: str,
    to_city: str,
    date: str,
    *,
    preferred_window: tuple[time, time] | None = None,
) -> TrainOption | None:
    """Best train of the day.

    With a preferred window: the departure closest to the window start among
    trains departing inside the window. Without: the earliest departure.
    A given window with no in-window train returns None — the caller
    degrades (e.g. hands off to 12306 without a pre-picked train); we never
    silently substitute a train from outside the window.
    """
    options = await service.search(from_city, to_city, date)
    if preferred_window is None:
        return min(options, key=lambda o: o.dep_time) if options else None
    lo, hi = preferred_window
    in_window = [o for o in options if lo <= o.dep_time <= hi]
    return min(in_window, key=lambda o: o.dep_time) if in_window else None


async def build_transfer_item(
    service: TrainService,
    *,
    from_city: str,
    to_city: str,
    date: str,
    day: int,
    seq: int,
    item_id: str,
    preferred_window: tuple[time, time] | None = None,
) -> TransferItem | None:
    """Pick the best train and convert it into a TransferItem.

    Cross-midnight approximation: TransferItem carries only time-of-day
    fields (models.py has no date on items), so a train arriving the next
    day (arr_time < dep_time) gets end_time truncated to 23:59 — the
    arrival spilling past the day boundary is intentionally approximate.
    Returns None when no train qualifies (caller degrades).
    """
    best = await pick_best_train(
        service, from_city, to_city, date, preferred_window=preferred_window
    )
    if best is None:
        return None
    end_time = best.arr_time if best.arr_time >= best.dep_time else time(23, 59)
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=seq,
        from_city=from_city,
        to_city=to_city,
        mode="train",
        start_time=best.dep_time,
        end_time=end_time,
        duration_minutes=best.duration_minutes,
        train_no=best.train_no,
    )
