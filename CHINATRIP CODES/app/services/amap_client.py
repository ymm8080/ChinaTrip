import logging

import httpx

logger = logging.getLogger(__name__)


class AmapError(Exception):
    """Amap API error. Message must never contain the api key."""

    def __init__(self, message: str, infocode: str = "") -> None:
        super().__init__(message)
        self.infocode = infocode


class AmapTimeoutError(AmapError):
    pass


class AmapQuotaExhaustedError(AmapError):
    """infocode 10021 (USER_DAILY_QUERY_OVER_LIMIT)：当日配额用尽。

    2026-10-24 实测 /place/text 与 /place/around 是独立配额池，
    text 尽时 around 仍可用；调用方据此停止重试或改道。
    """


def _is_quota_exhausted(data: dict) -> bool:
    # infocode=10021 为主判据；info 含 OVER_LIMIT 兜底（防个别响应缺 infocode）。
    if _as_str(data.get("infocode")) == "10021":
        return True
    return "OVER_LIMIT" in (_as_str(data.get("info")) or "")


def _as_str(value: object) -> str | None:
    # Amap returns [] instead of "" for some empty string fields.
    return value if isinstance(value, str) else None


def _parse_location(value: str | None) -> dict | None:
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        return {"lon": float(parts[0]), "lat": float(parts[1])}
    except ValueError:
        return None


def _parse_int(value: object, default: int | None = None) -> int | None:
    # Amap sends numeric fields as strings (and [] instead of "" when blank).
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _parse_float(value: object, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _parse_polyline(value: str | None) -> list[dict]:
    if not value:
        return []
    points = [_parse_location(chunk) for chunk in value.split(";")]
    return [p for p in points if p is not None]


def _normalize_regeo(data: dict) -> dict:
    regeocode = data.get("regeocode")
    reg = regeocode if isinstance(regeocode, dict) else {}
    comp = reg.get("addressComponent")
    comp = comp if isinstance(comp, dict) else {}
    province = _as_str(comp.get("province"))
    # Municipalities answer city=[] (empty list, not string); province carries it.
    city = _as_str(comp.get("city")) or province
    return {
        "country": _as_str(comp.get("country")),
        "province": province,
        "city": city,
        "district": _as_str(comp.get("district")),
        "address": _as_str(reg.get("formatted_address")),
    }


def _normalize_photos(photos: object) -> list[dict]:
    # v3/v5 photos 形状一致：[{title, url}]；无 url（含空串/[]）的元素丢弃。
    if not isinstance(photos, list):
        return []
    out: list[dict] = []
    for item in photos:
        if not isinstance(item, dict):
            continue
        url = _as_str(item.get("url"))
        if not url:
            continue
        out.append({"url": url, "title": _as_str(item.get("title"))})
    return out


def _normalize_poi(poi: dict) -> dict:
    city = _as_str(poi.get("cityname")) or _as_str(poi.get("pname"))
    biz = poi.get("biz_ext")
    biz = biz if isinstance(biz, dict) else {}
    normalized = {
        "source": "amap",
        "source_poi_id": _as_str(poi.get("id")),
        "name": _as_str(poi.get("name")),
        "city": city,
        "category": _as_str(poi.get("type")),
        "address": _as_str(poi.get("address")),
        "location": _parse_location(_as_str(poi.get("location"))),
        # v3 carries hours in biz_ext.opening; v5-style payloads put
        # them at the top level — accept both before giving up.
        "opening_hours": (
            _as_str(biz.get("opening"))
            or _as_str(poi.get("opentime_today"))
            or _as_str(poi.get("opentime"))
        ),
        "rating": _as_str(biz.get("rating")),
        # /place/around 带回的直线距离（米，字符串）；text 结果无此字段
        "distance": _as_str(poi.get("distance")),
    }
    # 空列表不落键：回源侧 hit.get("photos") 判空即可，不覆盖已有 wikimedia 照片
    photos = _normalize_photos(poi.get("photos"))
    if photos:
        normalized["photos"] = photos
    return normalized


def _extras(poi: dict) -> dict:
    """0009 富化字段（A2/A3/B1）：photos/tel/business_area——空值不落键，
    回源侧 hit.get(...) 判空即可（只填空语义在 store.upsert 兜底）。"""
    out: dict = {}
    photos = _normalize_photos(poi.get("photos"))
    if photos:
        out["photos"] = photos
    tel = _as_str(poi.get("tel"))
    if tel:
        out["tel"] = tel
    ba = poi.get("business_area")
    if isinstance(ba, list) and ba:
        first = _as_str(ba[0])
        if first:
            out["business_area"] = first
    return out


def _hours_result(poi: dict | None) -> dict:
    # v5 business 字段 -> search_hours 结果；无命中时保持三键旧形状。
    if poi is None:
        return {"opening_hours": None, "rating": None, "matched": None}
    biz = poi.get("business") if isinstance(poi.get("business"), dict) else {}
    hours = (
        _as_str(biz.get("opentime_week"))
        or _as_str(biz.get("opentime_today"))
        or _as_str(biz.get("opentime"))
    )
    result = {
        "opening_hours": hours,
        "rating": _as_str(biz.get("rating")),
        "matched": _as_str(poi.get("name")),
        "address": _as_str(poi.get("address")),
        "poi_id": _as_str(poi.get("id")),
    }
    result.update(_extras(poi))
    return result


def _normalize_walking_step(step: dict) -> dict:
    # Real v3 payload names the per-step distance "distance"; older docs say
    # "step_distance", so accept both.
    distance = _parse_int(step.get("distance"))
    if distance is None:
        distance = _parse_int(step.get("step_distance"), default=0)
    return {
        "instruction": _as_str(step.get("instruction")) or "",
        "road": _as_str(step.get("road")),
        "distance_m": distance,
        "orientation": _as_str(step.get("orientation")),
        "polyline": _parse_polyline(_as_str(step.get("polyline"))),
    }


def _stop_name(stop: object) -> str | None:
    return _as_str(stop.get("name")) if isinstance(stop, dict) else None


def _normalize_ride(kind: str, line: dict) -> dict:
    return {
        "kind": kind,
        "name": _as_str(line.get("name")) or "",
        "type": _as_str(line.get("type")),
        "departure_stop": _stop_name(line.get("departure_stop")),
        "arrival_stop": _stop_name(line.get("arrival_stop")),
        "via_stops": _parse_int(line.get("via_num"), default=0),
        "departure_time": _as_str(line.get("departure_time")),
    }


def _normalize_rides(container: object, keys: tuple[str, ...], kind: str) -> list[dict]:
    if not isinstance(container, dict):
        return []
    for key in keys:
        lines = container.get(key)
        if isinstance(lines, list):
            return [
                _normalize_ride(kind, line) for line in lines if isinstance(line, dict)
            ]
    return []


def _normalize_live(live: dict) -> dict:
    return {
        "kind": "live",
        "city": _as_str(live.get("city")),
        "adcode": _as_str(live.get("adcode")),
        "report_time": _as_str(live.get("reporttime")),
        "payload": {
            "weather": _as_str(live.get("weather")),
            "temperature": _as_str(live.get("temperature")),
            "wind_direction": _as_str(live.get("winddirection")),
            "wind_power": _as_str(live.get("windpower")),
            "humidity": _as_str(live.get("humidity")),
        },
    }


def _normalize_forecast(forecast: dict) -> dict:
    raw_casts = forecast.get("casts")
    casts = (
        [
            {
                "date": _as_str(c.get("date")),
                "day_weather": _as_str(c.get("dayweather")),
                "night_weather": _as_str(c.get("nightweather")),
                "day_temp": _as_str(c.get("daytemp")),
                "night_temp": _as_str(c.get("nighttemp")),
                "day_wind": _as_str(c.get("daywind")),
                "day_wind_power": _as_str(c.get("daypower")),
            }
            for c in raw_casts
            if isinstance(c, dict)
        ]
        if isinstance(raw_casts, list)
        else []
    )
    return {
        "kind": "forecast",
        "city": _as_str(forecast.get("city")),
        "adcode": _as_str(forecast.get("adcode")),
        "report_time": _as_str(forecast.get("reporttime")),
        "payload": {"casts": casts},
    }


def _normalize_transit_segment(segment: dict) -> dict:
    walking = segment.get("walking")
    walking_part = None
    if isinstance(walking, dict):
        raw_steps = walking.get("steps")
        steps = (
            [_normalize_walking_step(s) for s in raw_steps if isinstance(s, dict)]
            if isinstance(raw_steps, list)
            else []
        )
        walking_part = {
            "distance_m": _parse_int(walking.get("distance"), default=0),
            "duration_s": _parse_int(walking.get("duration")),
            "steps": steps,
        }
    rides = [
        *_normalize_rides(segment.get("bus"), ("buslines",), "bus"),
        *_normalize_rides(segment.get("railway"), ("railways", "buslines"), "railway"),
    ]
    return {"walking": walking_part, "rides": rides}


class AmapClient:
    # 图商标识（2026-10-28 一键切图商）：leg_source 等按真实 vendor 标注。
    vendor = "amap"

    def __init__(
        self,
        *,
        key: str,
        base_url: str = "https://restapi.amap.com/v3",
        timeout_seconds: float = 5.0,
        route_timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        # 路线规划（direction/*）比 POI/地理编码慢，允许单独放宽
        self._route_timeout_seconds = route_timeout_seconds or timeout_seconds
        self._transport = transport
        # v5 endpoints (richer business hours) live beside the v3 base
        self._v5_base = self._base_url.rsplit("/v3", 1)[0] + "/v5"

    async def _request_json(
        self, path: str, params: dict[str, str], *, timeout_seconds: float | None = None
    ) -> dict:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds or self._timeout_seconds,
            transport=self._transport,
        ) as http:
            try:
                response = await http.get(path, params=params)
            except httpx.TimeoutException as exc:
                raise AmapTimeoutError("amap request timed out") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise AmapError("amap returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise AmapError("amap returned unexpected JSON shape")
        if data.get("status") != "1":
            if _is_quota_exhausted(data):
                raise AmapQuotaExhaustedError(
                    _as_str(data.get("info")) or "amap daily quota exhausted",
                    _as_str(data.get("infocode")) or "",
                )
            raise AmapError(
                _as_str(data.get("info")) or "amap request failed",
                _as_str(data.get("infocode")) or "",
            )
        return data

    async def search_poi(
        self, keywords: str, *, city: str | None = None, page: int = 1
    ) -> list[dict]:
        params: dict[str, str | int] = {
            "key": self._key,
            "keywords": keywords,
            "offset": 10,
            "page": page,
            "output": "JSON",
            "extensions": "all",
        }
        if city:
            params["city"] = city
            params["citylimit"] = "true"
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as http:
            try:
                response = await http.get("/place/text", params=params)
            except httpx.TimeoutException as exc:
                raise AmapTimeoutError("amap request timed out") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise AmapError("amap returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise AmapError("amap returned unexpected JSON shape")
        if data.get("status") != "1":
            if _is_quota_exhausted(data):
                raise AmapQuotaExhaustedError(
                    _as_str(data.get("info")) or "amap daily quota exhausted",
                    _as_str(data.get("infocode")) or "",
                )
            raise AmapError(
                _as_str(data.get("info")) or "amap request failed",
                _as_str(data.get("infocode")) or "",
            )
        pois = data.get("pois")
        if not isinstance(pois, list):
            return []
        return [_normalize_poi(p) for p in pois if isinstance(p, dict)]

    async def search_poi_around(
        self,
        keywords: str,
        *,
        location: str,
        radius: int = 30000,
        page: int = 1,
        offset: int = 25,
    ) -> list[dict]:
        """/place/around — 关键字+坐标+半径。2026-10-24 实测：与 /place/text
        是独立配额池（text 已 USER_DAILY_QUERY_OVER_LIMIT 当天 around 仍
        OK），默认综合排序（权重≈知名度），不传 sortrule=distance。"""
        params: dict[str, str | int] = {
            "key": self._key,
            "keywords": keywords,
            "location": location,
            "radius": radius,
            "offset": offset,
            "page": page,
            "output": "JSON",
            "extensions": "all",
        }
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as http:
            try:
                response = await http.get("/place/around", params=params)
            except httpx.TimeoutException as exc:
                raise AmapTimeoutError("amap request timed out") from exc
        return self._pois_from_response(response)

    @staticmethod
    def _pois_from_response(response: httpx.Response) -> list[dict]:
        try:
            data = response.json()
        except ValueError as exc:
            raise AmapError("amap returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise AmapError("amap returned unexpected JSON shape")
        if data.get("status") != "1":
            if _is_quota_exhausted(data):
                raise AmapQuotaExhaustedError(
                    _as_str(data.get("info")) or "amap daily quota exhausted",
                    _as_str(data.get("infocode")) or "",
                )
            raise AmapError(
                _as_str(data.get("info")) or "amap request failed",
                _as_str(data.get("infocode")) or "",
            )
        pois = data.get("pois")
        if not isinstance(pois, list):
            return []
        return [_normalize_poi(p) for p in pois if isinstance(p, dict)]

    async def regeo(self, *, lon: float, lat: float) -> dict:
        params = {
            "key": self._key,
            "location": f"{lon:.6f},{lat:.6f}",
            "output": "JSON",
            "extensions": "base",
        }
        data = await self._request_json("/geocode/regeo", params)
        return _normalize_regeo(data)

    async def ip_locate(self) -> dict:
        # Amap resolves the caller by source IP; our server's egress IP is the
        # user's network, so no ip param is passed on purpose.
        params = {"key": self._key, "output": "JSON"}
        data = await self._request_json("/ip", params)
        province = _as_str(data.get("province"))
        return {
            "province": province,
            "city": _as_str(data.get("city")) or province,
            "adcode": _as_str(data.get("adcode")),
        }

    async def get_weather(self, adcode: str, *, extensions: str = "all") -> dict:
        """City weather (/weather/weatherInfo) — upstream is 中国气象局.

        extensions="base" -> live conditions (lives); "all" -> 3-day
        forecast (casts, today included). Amap updates live hourly and
        the forecast around 8/11/18 each day; callers schedule after
        those points. Returns {"kind","city","adcode","report_time",
        "payload"} or {} when Amap answers OK with no rows (some
        adcodes have no station).
        """
        data = await self._request_json(
            "/weather/weatherInfo",
            {
                "key": self._key,
                "city": adcode,
                "extensions": extensions,
                "output": "JSON",
            },
        )
        lives = data.get("lives")
        if isinstance(lives, list) and lives and isinstance(lives[0], dict):
            return _normalize_live(lives[0])
        forecasts = data.get("forecasts")
        if isinstance(forecasts, list) and forecasts and isinstance(forecasts[0], dict):
            return _normalize_forecast(forecasts[0])
        return {}

    async def walking_route(
        self,
        origin: str,
        destination: str,
        *,
        origin_id: str | None = None,
        destination_id: str | None = None,
    ) -> dict:
        # origin_id/destination_id (POI ids) are amap-recommended accuracy
        # boosters when the endpoints are POIs — measured: they snap the
        # route to doors/entrances instead of the raw coordinate.
        params = {
            "key": self._key,
            "origin": origin,
            "destination": destination,
            "output": "JSON",
        }
        if origin_id:
            params["origin_id"] = origin_id
        if destination_id:
            params["destination_id"] = destination_id
        data = await self._request_json(
            "/direction/walking", params, timeout_seconds=self._route_timeout_seconds
        )
        route = data.get("route")
        paths = route.get("paths") if isinstance(route, dict) else None
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
            # Same origin/destination is legal; Amap may answer with no paths.
            return {"distance_m": 0, "duration_s": None, "steps": [], "polyline": []}
        raw_steps = paths[0].get("steps")
        steps = (
            [_normalize_walking_step(s) for s in raw_steps if isinstance(s, dict)]
            if isinstance(raw_steps, list)
            else []
        )
        # Path-level distance/duration are authoritative; fall back to the
        # step sum when Amap omits them.
        distance_m = _parse_int(paths[0].get("distance"))
        if distance_m is None:
            distance_m = sum(step["distance_m"] for step in steps)
        return {
            "distance_m": distance_m,
            "duration_s": _parse_int(paths[0].get("duration")),
            "steps": steps,
            "polyline": [point for step in steps for point in step["polyline"]],
        }

    async def distance(
        self, origins: list[str], destination: str, *, type_: int = 1
    ) -> list[dict]:
        """Measure each origin -> destination pair (/distance).

        type_=1 walking. Up to 100 origins share one destination per call;
        results come back in origin order as {"distance_m", "duration_s"}.
        """
        params = {
            "key": self._key,
            "origins": "|".join(origins),
            "destination": destination,
            "type": str(type_),
            "output": "JSON",
        }
        data = await self._request_json("/distance", params)
        rows = data.get("results")
        if not isinstance(rows, list):
            return []
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "distance_m": _parse_int(row.get("distance")),
                    "duration_s": _parse_int(row.get("duration")),
                }
            )
        return out

    async def place_hours(self, poi_id: str) -> dict:
        """Fetch business hours for one POI (v5 place/detail).

        v5 carries far richer hours than the v3 search payload —
        opentime_week includes closing days, last entry and holiday
        windows (e.g. 三峡博物馆 "周二–周日 09:00–17:00 …周一不开放").
        Returns {"opening_hours": str | None, "rating": str | None}.
        """
        data = await self._request_json(
            f"{self._v5_base}/place/detail",
            {
                "key": self._key,
                "id": poi_id,
                "show_fields": "business,photos",
                "output": "JSON",
            },
        )
        poi = data.get("poi") if isinstance(data.get("poi"), dict) else None
        if poi is None:
            pois = data.get("pois")
            if isinstance(pois, list) and pois and isinstance(pois[0], dict):
                poi = pois[0]
        if poi is None:
            return {"opening_hours": None, "rating": None}
        biz = poi.get("business") if isinstance(poi.get("business"), dict) else {}
        hours = (
            _as_str(biz.get("opentime_week"))
            or _as_str(biz.get("opentime_today"))
            or _as_str(biz.get("opentime"))
        )
        result = {
            "opening_hours": hours,
            "rating": _as_str(biz.get("rating")),
            "address": _as_str(poi.get("address")),
        }
        result.update(_extras(poi))
        return result

    async def search_hours(
        self, keyword: str, city: str | None = None, *, location: str | None = None
    ) -> dict:
        """Last-resort opening-hours lookup by name (v5 place/text).

        Covers items without a poi_id (manual adds, link-extracted
        sites): one keyword query, first hit only. Same shape as
        place_hours() plus the matched POI name.

        text 配额尽（10021）且调用方给了 location 时，改道 v5
        /place/around 再试一次（独立配额池，radius 3km 内首条命中）；
        around 也失败则回抛 text 的原始异常。
        """
        params = {
            "key": self._key,
            "keywords": keyword,
            "page_size": "1",
            "show_fields": "business,photos",
            "output": "JSON",
        }
        if city:
            params["city"] = city
            params["city_limit"] = "true"
        try:
            data = await self._request_json(f"{self._v5_base}/place/text", params)
        except AmapQuotaExhaustedError as exc:
            if not location:
                raise
            logger.warning(
                "amap: text quota exhausted for hours, degrading to around, keyword=%s",
                keyword,
            )
            try:
                return await self._search_hours_around(keyword, location)
            except Exception:
                # around 失败（含其配额也尽/超时）一律回抛 text 原始异常
                logger.warning(
                    "amap: around fallback failed for hours, keyword=%s",
                    keyword,
                    exc_info=True,
                )
                raise exc
        pois = data.get("pois")
        poi = None
        if isinstance(pois, list) and pois and isinstance(pois[0], dict):
            poi = pois[0]
        return _hours_result(poi)

    async def _search_hours_around(self, keyword: str, location: str) -> dict:
        """search_hours 的 10021 兜底：v5 /place/around 取坐标邻近首条。"""
        params = {
            "key": self._key,
            "keywords": keyword,
            "location": location,
            "radius": "3000",
            "page_size": "1",
            "show_fields": "business,photos",
            "output": "JSON",
        }
        data = await self._request_json(f"{self._v5_base}/place/around", params)
        pois = data.get("pois")
        poi = None
        if isinstance(pois, list) and pois and isinstance(pois[0], dict):
            poi = pois[0]
        return _hours_result(poi)

    async def transit_route(
        self,
        origin: str,
        destination: str,
        *,
        city: str,
        cityd: str | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {
            "key": self._key,
            "origin": origin,
            "destination": destination,
            "city": city,
            "output": "JSON",
        }
        if cityd:
            params["cityd"] = cityd
        data = await self._request_json(
            "/direction/transit/integrated",
            params,
            timeout_seconds=self._route_timeout_seconds,
        )
        route = data.get("route")
        transits = route.get("transits") if isinstance(route, dict) else None
        if not isinstance(transits, list):
            return []
        plans = []
        for transit in transits[:3]:
            if not isinstance(transit, dict):
                continue
            raw_segments = transit.get("segments")
            segments = (
                [
                    _normalize_transit_segment(s)
                    for s in raw_segments
                    if isinstance(s, dict)
                ]
                if isinstance(raw_segments, list)
                else []
            )
            plans.append(
                {
                    "cost_yuan": _parse_float(transit.get("cost")),
                    "duration_s": _parse_int(transit.get("duration")),
                    "walking_distance_m": _parse_int(transit.get("walking_distance")),
                    "segments": segments,
                }
            )
        return plans
