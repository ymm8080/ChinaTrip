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

import logging
import re
from datetime import date as _date
from datetime import time, timedelta
from itertools import product
from typing import NamedTuple, Protocol

import httpx
from pydantic import BaseModel

from app.services.itinerary.models import TransferItem

logger = logging.getLogger(__name__)


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


# --- remote sources: 数据源链 携程 > 美团 > 12306 > mock（v2.4 行程中心） ---


class TrainSourceError(Exception):
    """链上任一数据源失败（网络/反爬/解析）。链内消化，绝不外抛到规划链。"""


class TrainSource(Protocol):
    """链上任一数据源：成功返回班次列表（可为空=该源无票），失败抛异常。"""

    name: str

    async def fetch(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]: ...


# 携程 H5 探测证据（2026-10-18，浏览器 UA 直探）：
#   trains.ctrip.com/trainbooking/search -> 200 但为 456KB JS 渲染 SPA 壳，
#     服务端直 GET 无班次数据（数据走需页面签名的 soa2 接口）；
#   m.ctrip.com/restapi/soa2/14666/json/GetBookingByTrainV3 -> 403
#     {"status":"failed","code":"11010","message":"Operation Forbidden."}；
#   trains.ctrip.com/pages/booking/trainList -> 404。
# 结论：个人开发者无公开火车票 API，反爬签名拦截；商务合作拿到授权接口后
# 填真实现即可。
_CTRIP_PROBE_EVIDENCE = (
    "H5 probe 2026-10-18: restapi/soa2/14666 GetBookingByTrainV3 -> 403 "
    "Operation Forbidden (code 11010); trainbooking/search -> JS-rendered SPA "
    "shell, no server-side train data; no public API for individual developers"
)


class CtripTrainSource:
    """携程火车票源（占位）：探测结论=反爬签名拦截，链内自动跳过。"""

    name = "ctrip"

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds  # 预留：真实实现接入时使用

    async def fetch(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]:
        raise TrainSourceError(f"ctrip source unavailable ({_CTRIP_PROBE_EVIDENCE})")


# 美团 H5 探测证据（2026-10-18，浏览器 UA 直探）：
#   i.meituan.com/train/searchList -> 400 Bad Message（无此公开端点）；
#   train.meituan.com -> DNS 不可解析（域名不存在）；
#   i.meituan.com 其余通道 -> 303 跳登录。
# 结论：无公开火车票 API；美团火车票由第三方供应商承接（链路不开放）。
_MEITUAN_PROBE_EVIDENCE = (
    "H5 probe 2026-10-18: i.meituan.com/train/searchList -> 400 Bad Message; "
    "train.meituan.com -> DNS unresolved; no public train API (meituan train "
    "inventory is third-party supplied, not open)"
)


class MeituanTrainSource:
    """美团火车票源（占位）：探测结论=无公开端点，链内自动跳过。"""

    name = "meituan"

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds  # 预留：真实实现接入时使用

    async def fetch(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]:
        raise TrainSourceError(
            f"meituan source unavailable ({_MEITUAN_PROBE_EVIDENCE})"
        )


# --- 12306 源（无需 key，链内实际主力） ---

_12306_BASE_URL = "https://kyfw.12306.cn"
_STATION_JS_PATH = "/otn/resources/js/framework/station_name.js"
# 12306 轮换余票查询路径；按序尝试直到 200 且 JSON 含 data.result。
_LEFT_TICKET_PATHS = ("query", "queryA", "queryG", "queryZ", "queryU", "queryE")
_MAX_QUERY_COMBOS = 6  # from 候选站 × to 候选站 的查询预算（优先站名==城市）
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _parse_hhmm(value: str) -> time | None:
    """"07:00" -> time(7, 0)。12306 用 24:00 表次日零点，截到 23:59。"""
    match = _HHMM_RE.match(value.strip())
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour == 24 and minute == 0:
        return time(23, 59)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _redirect_hint(response: httpx.Response) -> str | None:
    """错路径的 302 JSON 体 {"c_url": "leftTicket/queryG"} -> "queryG"。

    非 JSON 体（403 HTML 等）返回 None；c_url 前缀不符返回 None（防注入
    任意路径，只认 leftTicket 家族内的尾段）。
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    c_url = payload.get("c_url")
    if isinstance(c_url, str) and c_url.startswith("leftTicket/"):
        tail = c_url[len("leftTicket/"):].strip("/")
        return tail or None
    return None


def _parse_station_js(text: str) -> dict[str, str]:
    """station_name.js -> {站名: 电报码}。

    条目形如 ``@bjb|北京北|VAP|beijingbei|bjb|0|0357|...``（竖线 split 后
    第 2 段=站名、第 3 段=电报码）。畸形条目逐条跳过，不因个别坏行弃整表。
    """
    stations: dict[str, str] = {}
    for chunk in text.split("@"):
        parts = chunk.split("|")
        if len(parts) < 3:
            continue
        name, telecode = parts[1].strip(), parts[2].strip()
        if name and telecode and len(telecode) <= 5 and telecode.isascii():
            stations[name] = telecode
    return stations


def _city_station_names(stations: dict[str, str], city: str) -> list[str]:
    """城市 -> 候选站名：站名==城市 优先，其余站名以城市名开头的全部收集。

    北京 -> [北京, 北京东, 北京北, ...]；丰台/朝阳这类不以城市名开头的站
    不在候选内（组合预算有限，宁缺毋滥）。单站城市只返回自身。
    """
    exact = [city] if city in stations else []
    prefixed = sorted(s for s in stations if s.startswith(city) and s != city)
    return exact + prefixed


def _time_candidates(row: list[str], station: str) -> list[tuple[int, time]]:
    """站名锚点：行内每个等于站名的字段，其后 3 个字段内的 HH:MM 候选。

    12306 result 行的时间字段下标历年漂移（6/7 时而是全程、时而是所查区间
    的站名），绝不硬编码时间下标——只信"站名锚点 + 邻近时间字段"。窗口 3
    同时覆盖 [站名, 时间] 与 [站名, 站名, 时间] 两种排布（后者见 6=始发站/
    7=终到站/8=时刻 的经典布局）。
    """
    candidates: list[tuple[int, time]] = []
    for i, value in enumerate(row):
        if value != station:
            continue
        for k in range(1, 4):
            if i + k >= len(row):
                break
            parsed = _parse_hhmm(row[i + k])
            if parsed is not None:
                candidates.append((i + k, parsed))
    return candidates


def _pick_time_pair(
    dep_candidates: list[tuple[int, time]],
    arr_candidates: list[tuple[int, time]],
) -> tuple[time, time] | None:
    """从锚点候选里选 (出发, 到达) 时刻对。

    出发/到达时间字段在 result 行内恒相邻，故优先取相邻字段对，否则取字段
    位次最小的一对；同字段或同值的候选对一律排除——锚不稳就不返回该班
    （宁可少返回几班，不能返回错时刻）。
    """
    pairs = [
        (dep, arr)
        for dep in dep_candidates
        for arr in arr_candidates
        if arr[0] != dep[0] and arr[1] != dep[1]
    ]
    if not pairs:
        return None
    adjacent = [p for p in pairs if p[1][0] == p[0][0] + 1]
    dep, arr = min(adjacent or pairs, key=lambda p: (p[0][0], p[1][0]))
    return dep[1], arr[1]


def _row_to_option(
    row: list[str],
    from_station: str,
    to_station: str,
    from_city: str,
    to_city: str,
    query_date: str,
) -> TrainOption | None:
    """result 行 -> TrainOption；锚不到时刻返回 None（该班跳过）。

    车次取下标 3（station_train_code，历年稳定）；历时用锚定到的出发/到达
    时刻差（跨零点由 _duration_minutes 补 24h）。
    """
    if len(row) < 4 or not row[3]:
        return None
    pair = _pick_time_pair(
        _time_candidates(row, from_station),
        _time_candidates(row, to_station),
    )
    if pair is None:
        return None
    dep, arr = pair
    return TrainOption(
        train_no=row[3],
        dep_time=dep,
        arr_time=arr,
        duration_minutes=_duration_minutes(dep, arr),
        from_station=from_station,
        to_station=to_station,
        from_city=from_city,
        to_city=to_city,
        date=query_date,
    )


class Train12306Source:
    """12306 余票/时刻查询源（无需 key）。

    站点电报码表每实例只拉一次（get_train_service 进程级单例下即进程一次）；
    余票查询前先碰一次余票首页拿会话 cookie（httpx cookie jar 自动携带，
    失败不阻断）。超时立即判源失败——网络黑洞下换路径/组合大概率同样超时，
    快速降级比硬重试好。
    """

    name = "12306"

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport  # 测试注入 httpx.MockTransport
        self._stations: dict[str, str] | None = None
        self._active_path: str | None = None  # 记住本进程命中的查询路径

    async def fetch(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]:
        # 规划场景可能传空日期：班次表日内基本稳定，用 today+3 占位查询。
        query_date = date.strip() or (_date.today() + timedelta(days=3)).isoformat()
        if from_city == to_city:
            return []
        async with httpx.AsyncClient(
            base_url=_12306_BASE_URL,
            timeout=self._timeout_seconds,
            headers={"User-Agent": _BROWSER_UA},
            transport=self._transport,
            follow_redirects=True,
        ) as client:
            try:
                await client.get("/otn/leftTicket/init")
            except httpx.HTTPError:
                pass  # 部分时段 12306 无 cookie 也放行查询
            stations = await self._load_stations(client)
            from_names = _city_station_names(stations, from_city)
            to_names = _city_station_names(stations, to_city)
            if not from_names or not to_names:
                return []
            combos = list(product(from_names, to_names))[:_MAX_QUERY_COMBOS]
            options: list[TrainOption] = []
            seen: set[tuple[str, time, str]] = set()
            for from_station, to_station in combos:
                rows = await self._query_rows(
                    client,
                    query_date,
                    stations[from_station],
                    stations[to_station],
                )
                for row in rows:
                    option = _row_to_option(
                        row, from_station, to_station, from_city, to_city, query_date
                    )
                    if option is None:
                        continue
                    key = (option.train_no, option.dep_time, option.from_station)
                    if key in seen:
                        continue
                    seen.add(key)
                    options.append(option)
            options.sort(key=lambda o: o.dep_time)
            return options

    async def _load_stations(self, client: httpx.AsyncClient) -> dict[str, str]:
        if self._stations is not None:
            return self._stations
        response = await client.get(_STATION_JS_PATH)
        response.raise_for_status()
        stations = _parse_station_js(response.text)
        if not stations:
            raise TrainSourceError("station_name.js parsed to an empty table")
        self._stations = stations
        return stations

    async def _query_rows(
        self,
        client: httpx.AsyncClient,
        query_date: str,
        from_code: str,
        to_code: str,
    ) -> list[list[str]]:
        """一组电报码 -> result 行（split 后的字段表）。所有候选路径都失败
        则抛 TrainSourceError（由链降级；403/非 JSON 只算单路径失败）。

        错路径实测回 302 + JSON 体 {"c_url":"leftTicket/queryG",...}：按
        提示直跳当前活跃路径，避免整串候选轮询。
        """
        params = {
            "leftTicketDTO.train_date": query_date,
            "leftTicketDTO.from_station": from_code,
            "leftTicketDTO.to_station": to_code,
            "purpose_codes": "ADULT",
        }
        pending = [p for p in _LEFT_TICKET_PATHS if p != self._active_path]
        if self._active_path:
            pending.insert(0, self._active_path)  # 上个组合命中的路径优先
        tried: set[str] = set()
        while pending:
            path = pending.pop(0)
            if path in tried:
                continue
            tried.add(path)
            try:
                response = await client.get(
                    f"/otn/leftTicket/{path}", params=params
                )
            except httpx.TimeoutException as exc:
                raise TrainSourceError("12306 query timed out") from exc
            if response.status_code != 200:
                hint = _redirect_hint(response)
                if hint and hint not in tried and hint not in pending:
                    pending.insert(0, hint)
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            data = payload.get("data") if isinstance(payload, dict) else None
            result = data.get("result") if isinstance(data, dict) else None
            if not isinstance(result, list):
                continue
            self._active_path = path
            return [row.split("|") for row in result if isinstance(row, str)]
        raise TrainSourceError(
            f"all 12306 leftTicket paths failed for {from_code}->{to_code}"
        )


class RemoteTrainService(TrainService):
    """数据源链服务：按 sources 顺序尝试，任一源返回非空班次即用。

    全部源失败/为空 -> 降级 fallback（MockTrainService，已覆盖 8 对核心
    城市对）；再查不到由调用方已有的 flight/car 占位兜底。任何异常都在
    这里消化，绝不穿出到规划链。
    """

    def __init__(
        self, fallback: TrainService, *, sources: list[TrainSource]
    ) -> None:
        self._fallback = fallback
        self._sources = tuple(sources)
        # 最近一次 search 的命中来源标记：源名 / "mock"（降级兜底）/
        # None（尚未搜索）。缓存层落库时取它标注每行 provenance
        # （app/services/train_cache.py）。
        self.last_source: str | None = None

    async def search(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]:
        for source in self._sources:
            try:
                options = await source.fetch(from_city, to_city, date)
            except Exception as exc:  # 网络/反爬/解析：换下一个源
                logger.warning("train source %s failed: %s", source.name, exc)
                continue
            if options:
                self.last_source = source.name
                return options
            logger.info("train source %s returned no trains", source.name)
        self.last_source = "mock"
        return await self._fallback.search(from_city, to_city, date)


_SOURCE_FACTORIES = {
    "ctrip": CtripTrainSource,
    "meituan": MeituanTrainSource,
    "12306": Train12306Source,
}

_train_service_singleton: TrainService | None = None


def _build_remote_chain(settings) -> RemoteTrainService:
    """按 settings.travel_train_source_order 组装数据源链。

    get_train_service 与 train_cache 刷新作业共用同一套装配规则，
    避免两处各写一份源顺序逻辑。
    """
    sources = [
        _SOURCE_FACTORIES[name](timeout_seconds=settings.train_query_timeout_seconds)
        for name in settings.travel_train_source_order
        if name in _SOURCE_FACTORIES
    ]
    return RemoteTrainService(MockTrainService(), sources=sources)


def get_train_service(settings) -> TrainService:
    """统一注入点（api/plan、api/navigation、api/bookings、offer_cards）。

    settings 只需携带 train_remote_enabled / train_query_timeout_seconds /
    travel_train_source_order / train_cache_url / train_cache_ttl_hours
    （app.config.Settings 及测试替身皆可）。enabled=False 直接 mock、
    零网络零 DB IO；开启时远程链外包日批次缓存
    （app.services.train_cache.CachedTrainService），按进程级单例构造一次。
    """
    if not settings.train_remote_enabled:
        return MockTrainService()
    global _train_service_singleton
    if _train_service_singleton is None:
        # 延迟导入：train_cache 复用本模块的时刻表与链装配，模块级互导成环。
        from app.services.train_cache import create_cached_train_service

        _train_service_singleton = create_cached_train_service(settings)
    return _train_service_singleton


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
