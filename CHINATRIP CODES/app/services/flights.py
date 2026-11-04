"""航班转场服务（2026-10-28 用户拍板：飞机与火车同构安排）。

与火车同一套纪律：真实乘车日查询、开始日期+城市落定即预热
（prefetch_transfer_schedules）、选定班次的起降时刻/机场钉死进
TransferItem（solver 常量区间）。暂无公开航班时刻数据源（携程/飞常准/
航司均无个人开发者开放接口），MockFlightService 以确定性时刻表顶位：
去程/中转 09:00、返程偏好晚间 17:00——与既有占位语义逐位一致；真实源
接入只换 search 的 inner，管线零改动。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from app.services.itinerary.models import TransferItem


@dataclass(frozen=True)
class FlightOption:
    flight_no: str
    dep_time: time
    arr_time: time
    duration_minutes: int


class FlightService:
    """协议：search(from_city, to_city, date) -> 当日航班（date 原样透传）。"""

    async def search(
        self, from_city: str, to_city: str, date: str
    ) -> list[FlightOption]:
        raise NotImplementedError


class MockFlightService(FlightService):
    """确定性占位时刻表（09:00 / 17:00 两档，180 分钟门到门）。"""

    _OUTBOUND = FlightOption("MU1001", time(9, 0), time(12, 0), 180)
    _EVENING = FlightOption("MU1002", time(17, 0), time(20, 0), 180)

    async def search(
        self, from_city: str, to_city: str, date: str
    ) -> list[FlightOption]:
        if from_city == to_city:
            return []
        return [self._OUTBOUND, self._EVENING]


async def pick_best_flight(
    service: FlightService,
    from_city: str,
    to_city: str,
    date: str,
    *,
    preferred_window: tuple[time, time] | None = None,
) -> FlightOption | None:
    """与 pick_best_train 同语义：有窗取窗内最早，无窗取全天最早。

    给定窗口无窗内航班返回 None——调用方回退既有占位（绝不用窗外航班
    顶替窗口偏好）。
    """
    options = await service.search(from_city, to_city, date)
    if preferred_window is None:
        return min(options, key=lambda o: o.dep_time) if options else None
    lo, hi = preferred_window
    in_window = [o for o in options if lo <= o.dep_time <= hi]
    return min(in_window, key=lambda o: o.dep_time) if in_window else None


async def build_flight_transfer_item(
    service: FlightService,
    *,
    from_city: str,
    to_city: str,
    date: str,
    day: int,
    seq: int,
    item_id: str,
    preferred_window: tuple[time, time] | None = None,
) -> TransferItem | None:
    """与 build_transfer_item 同构：选中班次 → TransferItem(mode="flight")。

    Returns None when no flight qualifies — caller falls back to the train
    query (outbound/return preference) or the existing placeholder.
    """
    best = await pick_best_flight(
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
        mode="flight",
        start_time=best.dep_time,
        end_time=end_time,
        duration_minutes=best.duration_minutes,
        flight_no=best.flight_no,
    )
