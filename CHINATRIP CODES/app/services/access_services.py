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

import re
import time
from dataclasses import dataclass, field
from typing import Any

#: 城市级缓存（进程内 10 分钟）：一次规划里多张卡查同一城，避免反复打库。
_CACHE: dict[str, tuple[float, dict[tuple[str, str], list["Service"]]]] = {}
_CACHE_TTL_SECONDS = 600.0

#: 班次源由 agent 显式注入（与 poi_access.configure_profiles 同口径：
#: 规则层不隐式读库，测试与离线调用不被真实库污染）。
_STORE: Any | None = None

#: 官方严格模式（2026-11-16 用户拍板「Official only — deactivate map-vendor
#: timetables」）：只认 official_status=verified 的班次行；地图商实测的
#: 首末班一律当「没有时刻表」——排期退回纯打车模型，绝不拿未核实的窗
#: 去卡用户的时间。
STRICT_OFFICIAL = True


#: 流水发车但只给了首末班时的默认发车间隔（分钟）。15 分钟是景区专线常见档。
DEFAULT_HEADWAY_MINUTES = 15

#: 2026-11-23 用户拍板「any bus should be replaced by taxi」：常规公交
#: （mode=bus）一律不进候选与排期——某点只剩公交时 ``services_for`` 返回空，
#: 调用方自然回落打车链（hotel → 景点整段出租车）。景区直通车/旅游专线是
#: ``shuttle``、城际铁路是 ``train``、轮渡是 ``ferry``，均不在排除之列。
#: 与 ``app.services.trip_solver.live.BUS_MODES`` 保持同步（引擎侧同一口径）。
BUS_MODES = frozenset({"bus", "city_bus", "public_bus"})


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
    official_url: str | None = None
    official_status: str | None = None

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

    def returns(self) -> list[int]:
        """返程发车时刻（升序）。显式列表优先，缺则按返程首末班
        + 间隔展开发车（2026-11-16 回城三段）。"""
        if self.return_times:
            return sorted(self.return_times)
        first, last = self.return_first, self.return_last
        if first is None or last is None or last < first:
            return []
        step = self.return_frequency_minutes or DEFAULT_HEADWAY_MINUTES
        out: list[int] = []
        cursor = first
        while cursor <= last:
            out.append(cursor)
            cursor += max(5, step)
        return out

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
        official_url=row.get("official_url"),
        official_status=row.get("official_status"),
    )


def configure_store(store: Any | None) -> None:
    """注入班次源（PlanningAgent 初始化时调用；None = 关闭）。"""
    global _STORE
    _STORE = store
    _CACHE.clear()


def _is_official_row(row: dict[str, Any]) -> bool:
    """该班次行的时刻是否来自官方核实
    （official_status=verified 且 window_source=official）。
    """
    if str(row.get("official_status") or "").strip().lower() != "verified":
        return False
    source = str(row.get("window_source") or "").strip().lower()
    return source in ("", "official")


def is_official_poi(city: str | None, name: str | None) -> bool:
    """该点是否有官方核实的班次时刻（严格模式下决定要不要吃接驳链）。"""
    return bool(services_for(city, name))


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
        if STRICT_OFFICIAL and not _is_official_row(row):
            continue
        service = _to_service(row)
        out.setdefault((service.city, service.poi_name), []).append(service)
    _CACHE[key] = (now, out)
    return out


def is_bus_service(svc: Service) -> bool:
    """是否常规公交（用户 2026-11-23 拍板：一律改打车，不进候选）。"""
    return (getattr(svc, "mode", "") or "").strip().lower() in BUS_MODES


def services_for(city: str | None, name: str | None) -> list[Service]:
    """某点全部班次（先 (city, name)，再同名跨城兜底）。

    2026-11-23 用户拍板「any bus should be replaced by taxi」：常规公交
    （mode=bus）在此单点剔除，best_service / fastest_service / service_options
    等全部消费方口径一致——某点只剩公交时返回空表，调用方回落打车链。
    """
    if not name:
        return []
    table = city_services(city)
    items = table.get((str(city or ""), name)) or table.get(("", name)) or []
    return [svc for svc in items if not is_bus_service(svc)]


def best_service(city: str | None, name: str | None) -> Service | None:
    """取一条班次：优先有去程时刻表、车上分钟最长的（专线通常比公交快但班次少，
    这里按「有窗」优先，够排期用；多条并存时由调用方按窗判定再挑）。"""
    items = services_for(city, name)
    if not items:
        return None
    with_window = [s for s in items if s.outbound_first is not None or s.outbound_times]
    return (with_window or items)[0]


def fastest_service(
    city: str | None, name: str | None, *, arrive_boarding: int | None = None
) -> Service | None:
    """按「到乘车点后最快到景区」挑一条班次（2026-11-16 用户拍板
    「MOST TIME SAVING METHOD」）：逐条算 next_departure → 到景区时刻，
    取最早；并列时取票价低。没有时刻表时回落 best_service。"""
    items = services_for(city, name)
    if not items:
        return None
    if arrive_boarding is None:
        arrive_boarding = 9 * 60  # 用户口径：远郊专线通常 9 点前后
    best: Service | None = None
    best_key: tuple | None = None
    for svc in items:
        _verdict, _depart, arrive = svc.plan_leg(arrive_boarding)
        if arrive is None:
            continue
        key = (arrive, svc.fare_cny if svc.fare_cny is not None else 10**9)
        if best_key is None or key < best_key:
            best, best_key = svc, key
    return best or best_service(city, name)


def fastest_plan(
    city: str | None,
    name: str | None,
    board_minutes: int,
    *,
    ride_fallback: int | None = None,
    last_fallback: int | None = None,
) -> tuple[int, int, int, int] | None:
    """给定到乘车点时刻，挑「到景区最早」的一班（用户拍板 2026-11-16
    MOST TIME SAVING METHOD）。返回 (发车, 车上分钟, 落客步行分钟, 候车分钟)；
    没有官方时刻表返回 None（调用方退回档案经验值）。"""
    best: tuple[tuple[int, int], int, int, int] | None = None
    for svc in services_for(city, name):
        ride = int(svc.ride_minutes or ride_fallback or 0)
        last = int(svc.last_mile_minutes or last_fallback or 0)
        for depart in sorted(svc.departures()):
            if depart < int(board_minutes):
                continue
            key = (depart + ride + last, depart)
            if best is None or key < best[0]:
                best = (key, depart, ride, last)
    if best is None:
        return None
    _key, depart, ride, last = best
    return depart, ride, last, max(0, depart - int(board_minutes))


def fastest_return_plan(
    city: str | None,
    name: str | None,
    board_minutes: int,
    *,
    ride_fallback: int | None = None,
) -> tuple[int, int, int] | None:
    """给定「离开景区走回返程乘车点」的时刻，挑最快回市区的一班
    （2026-11-16 用户拍板「回城也是一样的接驳三段」的返向口径）。
    返回 (发车, 车上分钟, 候车分钟)；没有官方返程时刻表返回 None
    （调用方退档案经验值）。"""
    best: tuple[tuple[int, int], int, int] | None = None
    for svc in services_for(city, name):
        ride = int(svc.return_ride_minutes or svc.ride_minutes or ride_fallback or 0)
        for depart in sorted(svc.returns()):
            if depart < int(board_minutes):
                continue
            key = (depart + ride, depart)
            if best is None or key < best[0]:
                best = (key, depart, ride)
    if best is None:
        return None
    _key, depart, ride = best
    return depart, ride, max(0, depart - int(board_minutes))


def transfers_of(service_name: str | None) -> int:
    """线路名里的换乘次数：「（2 次换乘）」→ 2；没写按 0（直达线）。"""
    match = re.search(r"(\d+)\s*次换乘", str(service_name or ""))
    return int(match.group(1)) if match else 0


def service_options(
    city: str | None,
    name: str | None,
    *,
    board_minutes: int = 9 * 60,
    ride_fallback: int | None = None,
    last_fallback: int | None = None,
    wait_fallback: int = 0,
    taxi_minutes: Any = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """同一景点「不同方式」的候选块（2026-11-16 用户拍板：有接驳车/火车等
    不同方式时分 BLOCK 并排展示，默认选换乘少、时间短的）。

    每个官方班次行出一块；``taxi_minutes(coords)`` 由调用方注入（算到该
    乘车点的打车分钟，coords=None 时回 0）。排序键 = (换乘次数, 全程分钟,
    票价)，第一个即推荐项（recommended=True）。没有时刻表的行按档案经验
    值估全程，照样出块（乘车点/购票渠道/车程估算照展示，班次标注「以官网
    为准」）。
    """
    board0 = int(board_minutes if board_minutes is not None else 9 * 60)
    ranked: list[tuple[tuple, dict[str, Any]]] = []
    for svc in services_for(city, name):
        ride = int(svc.ride_minutes or ride_fallback or 0)
        last = int(
            svc.last_mile_minutes
            if svc.last_mile_minutes is not None
            else (last_fallback or 0)
        )
        coords = None
        if svc.boarding_lon is not None and svc.boarding_lat is not None:
            coords = (float(svc.boarding_lon), float(svc.boarding_lat))
        head = 0
        if taxi_minutes is not None:
            try:
                head = int(taxi_minutes(coords) or 0)
            except Exception:  # noqa: BLE001 - 打车估算失败不影响出块
                head = 0
        head = max(0, head)
        board = board0 + head
        depart = svc.next_departure(board)
        if depart is not None:
            wait = max(0, depart - board)
            has_tt = True
            arrive = depart + ride + last
        else:
            wait = max(0, int(wait_fallback or 0))
            has_tt = False
            arrive = board + wait + ride + last
        total = head + wait + ride + last
        fare = svc.fare_cny
        opt = {
            "mode": svc.mode or "shuttle",
            "service_name": svc.service_name,
            "operator": svc.operator,
            "boarding_stop": svc.boarding_stop,
            "boarding_lon": coords[0] if coords else None,
            "boarding_lat": coords[1] if coords else None,
            "alight_stop": svc.alight_stop,
            "taxi_minutes": head,
            "wait_minutes": wait,
            "ride_minutes": ride,
            "last_mile_minutes": last,
            "has_timetable": has_tt,
            "transfers": transfers_of(svc.service_name),
            "depart": fmt_minutes(depart) if depart is not None else None,
            "arrive": fmt_minutes(arrive) if arrive is not None else None,
            "departures": [fmt_minutes(m) for m in svc.departures() if fmt_minutes(m)],
            "returns": [fmt_minutes(m) for m in svc.return_times if fmt_minutes(m)],
            "fare_cny": fare,
            "fare_text": svc.fare_text(),
            "ticket_url": svc.ticket_url or svc.official_url,
            "official_url": svc.official_url or svc.ticket_url,
            "total_minutes": total,
        }
        key = (opt["transfers"], total, fare if fare is not None else 10**9)
        ranked.append((key, opt))
    ranked.sort(key=lambda pair: pair[0])
    out = [opt for _key, opt in ranked[: max(1, int(limit))]]
    if out:
        out[0]["recommended"] = True
    return out
