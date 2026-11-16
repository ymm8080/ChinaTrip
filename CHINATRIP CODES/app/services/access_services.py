"""远郊景区专线班次（poi_access_services，w12_0039）读口与排期口径。

用户口径（2026-11-16）：「远郊景区专线，无论火车还是直达巴士，需要先搜网络
或者高德地图数据拿到接驳的出发地点和时刻表、路途时间、到达时间、回程出发
时间、回城到达时间、票价、购票渠道，然后存入远郊景点交通 DATABASE。每次
运行 PLANNING 时候只需要加上 HOTEL 到接驳出发点的 TAXI 腿。」并且拍板
「班次服务窗建硬约束，超窗就换天/换方式」。

本模块只做三件事，全部是纯函数（时间单位=当天分钟数）：

* ``load(city)``：抓一次某城班次（源由 ``configure_store`` 注入，测试可喂假表）；
* ``Service.next_departure(after)`` / ``is_open(depart)``：窗判定；
* ``Service.plan_leg(arrive_boarding, ride_fallback)``：给定「到上车点的时刻」
  返回该走哪条腿——准点上车 / 等首班 / 已收车（调用方据此换天或换打车直达）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

#: 城市级缓存（进程内 10 分钟）：一次规划里多张卡查同一城，避免反复打库。
_CACHE: dict[str, tuple[float, dict[tuple[str, str], list["Service"]]]] = {}
_CACHE_TTL_SECONDS = 600.0

#: 班次源由 agent 显式注入（与 poi_access.configure_profiles 同口径：
#: 规则层不隐式读库，测试与离线调用不被真实库污染）。
_STORE: Any | None = None

#: 流水发车但只给了首末班时的默认发车间隔（分钟）。15 分钟是景区专线常见档。
DEFAULT_HEADWAY_MINUTES = 15


def _minutes(hhmm: str | None) -> int | None:
    """'07:30' → 450；脏值返回 None。"""
    if not hhmm:
        return None
    text = str(hhmm).strip().replace("：", ":")
    if ":" not in text:
        return None
    head, _, tail = text.partition(":")
    try:
        hour, minute = int(head), int(tail[:2])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def fmt_minutes(value: int | None) -> str | None:
    if value is None:
        return None
    return f"{value // 60:02d}:{value % 60:02d}"


@dataclass
class Service:
    """一条远郊专线（去程/回程时刻表 + 票价）。"""

    city: str
    poi_name: str
    mode: str
    service_name: str
    operator: str | None = None
    boarding_stop: str | None = None
    boarding_lon: float | None = None
    boarding_lat: float | None = None
    alight_stop: str | None = None
    outbound_times: list[int] = field(default_factory=list)
    outbound_first: int | None = None
    outbound_last: int | None = None
    outbound_frequency_minutes: int | None = None
    ride_minutes: int | None = None
    return_times: list[int] = field(default_factory=list)
    return_first: int | None = None
    return_last: int | None = None
    return_frequency_minutes: int | None = None
    return_ride_minutes: int | None = None
    return_arrive_last: str | None = None
    fare_cny: float | None = None
    fare_kind: str | None = None
    fare_note: str | None = None
    ticket_channel: str | None = None
    ticket_url: str | None = None
    last_mile_minutes: int | None = None
    note: str | None = None
    note_en: str | None = None
    source: str | None = None
    source_url: str | None = None

    # --- 窗判定 -------------------------------------------------------
    def departures(self) -> list[int]:
        """去程发车时刻（升序）。显式列表优先，缺则按首末班 + 间隔展开发车。"""
        if self.outbound_times:
            return sorted(self.outbound_times)
        first, last = self.outbound_first, self.outbound_last
        if first is None or last is None or last < first:
            return []
        step = self.outbound_frequency_minutes or DEFAULT_HEADWAY_MINUTES
        out: list[int] = []
        cursor = first
        while cursor <= last:
            out.append(cursor)
            cursor += max(5, step)
        return out

    def is_open(self, depart_minute: int) -> bool:
        """该时刻能否发车（落在首末班窗内）。"""
        if self.outbound_first is None and self.outbound_last is None:
            return True  # 无时刻表数据：不拦（调用方按均值链算）
        first = self.outbound_first
        last = self.outbound_last
        if first is not None and depart_minute < first:
            return False
        if last is not None and depart_minute > last:
            return False
        return True

    def next_departure(self, after_minute: int) -> int | None:
        """≥ after 的最早发车；当天没了返回 None。"""
        for depart in self.departures():
            if depart >= after_minute:
                return depart
        return None

    def last_departure(self) -> int | None:
        spans = self.departures()
        return spans[-1] if spans else self.outbound_last

    def first_departure(self) -> int | None:
        spans = self.departures()
        return spans[0] if spans else self.outbound_first

    # --- 排期 ---------------------------------------------------------
    def plan_leg(
        self, arrive_boarding: int, *, ride_fallback: int | None = None
    ) -> tuple[str, int, int | None]:
        """给定到上车点时刻，返回 (结论, 上车时刻, 到景区门口时刻)。

        结论三态：

        * ``"ok"``     —— 准点上车；
        * ``"early"``  —— 到得太早，等首班；
        * ``"closed"`` —— 当天已收车（调用方：换天 / 改打车直达）。

        ``ride_fallback`` = 没有车上分钟时的兜底（一般用档案均值）。
        """
        ride = self.ride_minutes or ride_fallback or 0
        last_mile = self.last_mile_minutes or 0
        depart = self.next_departure(arrive_boarding)
        if depart is None:
            return "closed", arrive_boarding, None
        first = self.first_departure()
        verdict = "early" if first is not None and arrive_boarding < first else "ok"
        return verdict, depart, depart + ride + last_mile

    def fare_text(self) -> str | None:
        if self.fare_cny is None and not self.fare_note:
            return None
        if self.fare_note:
            return self.fare_note
        kind = {"round_trip": "往返", "one_way": "单程", "free": ""}.get(
            self.fare_kind or "", ""
        )
        amount = f"{self.fare_cny:g} 元"
        return f"{kind} {amount}" if kind else amount


def _times(raw: Any) -> list[int]:
    return [m for m in (_minutes(t) for t in (raw or [])) if m is not None]


def _to_service(row: dict[str, Any]) -> Service:
    def _num(value: Any) -> float | None:
        return None if value is None else float(value)

    return Service(
        city=row["city"],
        poi_name=row["poi_name"],
        mode=row["mode"],
        service_name=row["service_name"],
        operator=row.get("operator"),
        boarding_stop=row.get("boarding_stop"),
        boarding_lon=_num(row.get("boarding_lon")),
        boarding_lat=_num(row.get("boarding_lat")),
        alight_stop=row.get("alight_stop"),
        outbound_times=_times(row.get("outbound_times")),
        outbound_first=_minutes(row.get("outbound_first")),
        outbound_last=_minutes(row.get("outbound_last")),
        outbound_frequency_minutes=row.get("outbound_frequency_minutes"),
        ride_minutes=row.get("ride_minutes"),
        return_times=_times(row.get("return_times")),
        return_first=_minutes(row.get("return_first")),
        return_last=_minutes(row.get("return_last")),
        return_frequency_minutes=row.get("return_frequency_minutes"),
        return_ride_minutes=row.get("return_ride_minutes"),
        return_arrive_last=row.get("return_arrive_last"),
        fare_cny=_num(row.get("fare_cny")),
        fare_kind=row.get("fare_kind"),
        fare_note=row.get("fare_note"),
        ticket_channel=row.get("ticket_channel"),
        ticket_url=row.get("ticket_url"),
        last_mile_minutes=row.get("last_mile_minutes"),
        note=row.get("note"),
        note_en=row.get("note_en"),
        source=row.get("source"),
        source_url=row.get("source_url"),
    )


def configure_store(store: Any | None) -> None:
    """注入班次源（PlanningAgent 初始化时调用；None = 关闭）。"""
    global _STORE
    _STORE = store
    _CACHE.clear()


def city_services(city: str | None) -> dict[tuple[str, str], list[Service]]:
    """某城全部班次，键 (city, poi_name)。源缺失/报错一律空表（退回均值链）。"""
    key = str(city or "").strip()
    store = _STORE
    if not key or store is None:
        return {}
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    try:
        rows = store.access_services([key]) or []
    except Exception:  # noqa: BLE001 — 班次读失败不能拦排程
        rows = []
    out: dict[tuple[str, str], list[Service]] = {}
    for row in rows:
        service = _to_service(row)
        out.setdefault((service.city, service.poi_name), []).append(service)
    _CACHE[key] = (now, out)
    return out


def services_for(city: str | None, name: str | None) -> list[Service]:
    """某点全部班次（先 (city, name)，再同名跨城兜底）。"""
    if not name:
        return []
    table = city_services(city)
    return table.get((str(city or ""), name)) or table.get(("", name)) or []


def best_service(city: str | None, name: str | None) -> Service | None:
    """取一条班次：优先有去程时刻表、车上分钟最长的（专线通常比公交快但班次少，
    这里按「有窗」优先，够排期用；多条并存时由调用方按窗判定再挑）。"""
    items = services_for(city, name)
    if not items:
        return None
    with_window = [s for s in items if s.outbound_first is not None or s.outbound_times]
    return (with_window or items)[0]
