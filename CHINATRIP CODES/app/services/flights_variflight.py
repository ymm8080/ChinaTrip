"""VariFlight 航班数据源适配骨架（2026-10-28 backlog：真实源只换 search inner）。

纪律与火车同门：settings.flight_api_key 为空 → build_flight_service 维持
MockFlightService（零网络零行为变化，测试/离线默认态）；配置 key 后规划
单例切到本适配器，pick_best_flight/转场管线零改动。城市→IATA 城市码映射
覆盖 KNOWN_CITIES 里通民航的城市（苏州/绍兴/嘉兴无民航机场不入表——search
直接 []，调用方回退占位，与 Mock 空班同义）。API 契约（路径/参数/字段名）
在 key 注册后按 open.variflight.com 文档校正；解析按 flights[].flightNo/
depTime/arrTime 防御性读取，任何异常/空响应降级 []——管线回退占位（与
pick_best_flight 返回 None 的占位语义一致），绝不抛错掀翻规划回合。
"""

from __future__ import annotations

import logging
import time
from datetime import time as dtime

import httpx

from app.services.flights import FlightOption, FlightService, MockFlightService

logger = logging.getLogger(__name__)

# KNOWN_CITIES → IATA 三字城市码（多机场城市用城市码：BJS/SHA/CTU…）。
# 无民航机场的 KNOWN_CITIES（苏州/绍兴/嘉兴）不入表。
CITY_AIRPORTS: dict[str, str] = {
    "北京": "BJS",
    "上海": "SHA",
    "广州": "CAN",
    "深圳": "SZX",
    "成都": "CTU",
    "杭州": "HGH",
    "重庆": "CKG",
    "西安": "SIA",
    "南京": "NKG",
    "武汉": "WUH",
    "厦门": "XMN",
    "青岛": "TAO",
    "大连": "DLC",
    "三亚": "SYX",
    "丽江": "LJG",
    "桂林": "KWL",
    "兰州": "LHW",
    "拉萨": "LXA",
    "昆明": "KMG",
    "大理": "DLU",
    "张家界": "DYG",
    "黄山": "TXN",
    "天津": "TSN",
    "长沙": "CSX",
    "郑州": "CGO",
    "济南": "TNA",
    "福州": "FOC",
    "泉州": "JJN",
    "威海": "WEH",
    "珠海": "ZUH",
    "哈尔滨": "HRB",
    "沈阳": "SHE",
    "长春": "CGQ",
    "无锡": "WUX",
    "洛阳": "LYA",
    "敦煌": "DNH",
    "舟山": "HSN",
}


def _bare(city: str) -> str:
    return (city or "").strip().removesuffix("市")


def _parse_hhmm(value: object) -> dtime | None:
    """「09:35」/「0935」→ time；解析不了返回 None（该行丢弃，不硬猜）。"""
    s = str(value or "").strip()
    if len(s) == 4 and s.isdigit():
        s = f"{s[:2]}:{s[2:]}"
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return dtime(h, m)


class VariFlightFlightService(FlightService):
    """VariFlight 适配器：search 查询 + 进程内 TTL 缓存 + 失败降级 []。

    调用方（pick_best_flight→转场管线）对 []/None 已有占位回退语义，
    本类永不 raise。缓存键 (城市码, 城市码, date)，命中即零 HTTP；
    过期/失败时如有陈旧缓存先顶上（时刻表旧一点好过占位）。
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://open-al.variflight.com",
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: float = 6 * 3600.0,
        cache: dict | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._ttl = cache_ttl_seconds
        # cache 外置可注入（测试断言命中/写回；进程内默认内存 dict）
        self._cache: dict[tuple[str, str, str], tuple[float, list[FlightOption]]] = (
            cache if cache is not None else {}
        )
        self._transport = transport

    async def search(
        self, from_city: str, to_city: str, date: str
    ) -> list[FlightOption]:
        if from_city == to_city:
            return []
        dep = CITY_AIRPORTS.get(_bare(from_city))
        arr = CITY_AIRPORTS.get(_bare(to_city))
        if not dep or not arr:
            return []
        key = (dep, arr, date)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        try:
            options = await self._fetch(dep, arr, date)
        except Exception:  # noqa: BLE001 — 任何失败降级占位，绝不掀翻规划
            logger.warning(
                "variflight: search %s→%s %s failed, degrading to placeholder",
                dep,
                arr,
                date,
                exc_info=True,
            )
            return hit[1] if hit is not None else []
        if options:
            self._cache[key] = (now + self._ttl, options)
        return options

    async def _fetch(self, dep: str, arr: str, date: str) -> list[FlightOption]:
        # 契约待校正（key 注册后按官方文档对齐路径/参数名）；解析与缓存
        # 已按最终形状写死，届时只改本方法里的一处请求构造。
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            resp = await client.get(
                "/api/searchflights",
                params={
                    "appid": self._api_key,
                    "departure": dep,
                    "arrival": arr,
                    "date": date,
                },
            )
            resp.raise_for_status()
            return self._parse(resp.json())

    @staticmethod
    def _parse(payload: object) -> list[FlightOption]:
        if not isinstance(payload, dict):
            return []
        rows = payload.get("flights")
        if not isinstance(rows, list):
            return []
        out: list[FlightOption] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            fno = str(row.get("flightNo") or row.get("flight_no") or "").strip()
            dep = _parse_hhmm(row.get("depTime") or row.get("dep_time"))
            arr = _parse_hhmm(row.get("arrTime") or row.get("arr_time"))
            if not fno or dep is None or arr is None:
                continue
            raw_dur = row.get("duration") or row.get("duration_minutes")
            try:
                minutes = int(raw_dur) if raw_dur is not None else None
            except (TypeError, ValueError):
                minutes = None
            if minutes is None or minutes <= 0:
                diff = (arr.hour * 60 + arr.minute) - (dep.hour * 60 + dep.minute)
                minutes = diff + 1440 if diff <= 0 else diff
            out.append(FlightOption(fno, dep, arr, minutes))
        return out


def build_flight_service(settings) -> FlightService:
    """装配入口（api/plan.py 单例与测试共用）：flight_api_key 空 → Mock
    （零行为变化），配置 key → VariFlight 适配器。"""
    key = (getattr(settings, "flight_api_key", "") or "").strip()
    if not key:
        return MockFlightService()
    return VariFlightFlightService(
        key,
        timeout_seconds=getattr(settings, "flight_api_timeout_seconds", 5.0),
    )
