"""百度地图 WebService 客户端——与 AmapClient 方法同构（鸭子类型）。

2026-10-27 迁移动机：高德开放平台商用技术费 5 万，前期小规模改走
百度个人认证免费配额（地点检索/路线规划各约 3 万次/日）。

约定：
- 异常复用 AmapError/AmapTimeoutError/AmapQuotaExhaustedError（从
  amap_client 导入）——API 层 except 子句与 detail 错误码零改动。
  百度 status 码：0 成功；301/302=配额（永久/当日）→Quota 系；
  20=ak 无效；210=IP 白名单；240=AK 未开通该服务（控制台勾选）。
- 坐标：库存统一 GCJ-02；百度收发一律 BD-09 且参数顺序是
  "lat,lng"（与高德相反）。换算全部收敛在本客户端边界（gcj02_to_bd09 /
  bd09_to_gcj02），数据库与调用方无感知。复用 amap_client 的
  _as_str/_parse_int 等容错解析（百度数值字段同样会以字符串混发）。
- 方向 v2 公交（transit）响应容器键名（routes/transits × steps/
  segments）文档页不可达未逐字段核实，两层候选键防御式解析；
  接 AK 后跑一次冒烟即可确认。
"""

import logging
import re

import httpx

from app.services.amap_client import (
    AmapError,
    AmapQuotaExhaustedError,
    AmapTimeoutError,
    _as_str,
    _parse_float,
    _parse_int,
    _parse_location,
)
from app.services.coords import bd09_to_gcj02, gcj02_to_bd09

logger = logging.getLogger(__name__)

# 百度 detail_info 的营业时间候选键（不同 POI 类目字段不一）
_HOURS_KEYS = ("opening_hours", "shop_hours", "opentime")


def _num(value: object) -> str | None:
    """'26°C'/'-2°C' -> '26'/'-2'；无数字返回 None。百度高低温带单位。"""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return m.group(0) if m else None


def _latlng(lon: float, lat: float) -> str:
    """GCJ-02 -> BD-09 并格式化成百度参数序（lat,lng，6 位小数）。"""
    b_lon, b_lat = gcj02_to_bd09(lon, lat)
    return f"{b_lat:.6f},{b_lon:.6f}"


def _gcj_point(point: object) -> dict | None:
    """百度 location{lat,lng}(BD-09) -> {"lon","lat"}(GCJ-02)。"""
    if not isinstance(point, dict):
        return None
    try:
        lon = float(point.get("lng"))
        lat = float(point.get("lat"))
    except (TypeError, ValueError):
        return None
    g_lon, g_lat = bd09_to_gcj02(lon, lat)
    return {"lon": g_lon, "lat": g_lat}


def _gcj_polyline(path: object) -> list[dict]:
    """百度 path('lng,lat;...'，BD-09) -> [{"lon","lat"}](GCJ-02)。"""
    if not path or not isinstance(path, str):
        return []
    out = []
    for chunk in path.split(";"):
        point = (
            _gcj_point({"lng": chunk.split(",")[0], "lat": chunk.split(",")[1]})
            if len(chunk.split(",")) == 2
            else None
        )
        if point:
            out.append(point)
    return out


class BaiduClient:
    # 图商标识（与 AmapClient.vendor 同构；方法级鸭子类型复用）。
    vendor = "baidu"

    def __init__(
        self,
        *,
        ak: str,
        base_url: str = "https://api.map.baidu.com",
        timeout_seconds: float = 5.0,
        route_timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._ak = ak
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        # 路线规划比检索慢，允许单独放宽——语义对齐 AmapClient
        self._route_timeout_seconds = route_timeout_seconds or timeout_seconds
        self._transport = transport

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
                raise AmapTimeoutError("baidu request timed out") from exc
            except httpx.RequestError as exc:
                raise AmapError(f"baidu network error: {type(exc).__name__}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise AmapError("baidu returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise AmapError("baidu returned unexpected JSON shape")
        status = data.get("status")
        if status != 0 and status != "0":
            message = _as_str(data.get("message")) or "baidu request failed"
            if str(status) in ("301", "302"):
                raise AmapQuotaExhaustedError(message, str(status))
            raise AmapError(message, str(status))
        return data

    # ---------- POI 检索 ----------

    async def search_poi(
        self, keywords: str, *, city: str | None = None, page: int = 1
    ) -> list[dict]:
        """/place/v2/search（text 模式：region 限定城市）。

        page 1 基（调用方口径）→ page_num 0 基（百度口径）。
        scope=2 带 detail_info（tag 类目 / overall_rating 评分 /
        营业时间候选键）。结果坐标 BD-09 → GCJ-02 后返回。
        """
        return await self._place_search(
            {"query": keywords, "region": city, "city_limit": "true"},
            page=page,
        )

    async def search_poi_around(
        self,
        keywords: str,
        *,
        location: str,
        radius: int = 30000,
        page: int = 1,
        offset: int = 25,
    ) -> list[dict]:
        """/place/v2/search（around 模式：location+radius）。

        location 入参为高德序 'lon,lat'（GCJ-02）——与 AmapClient 签名
        一致，内部换 BD-09 'lat,lng'。
        """
        origin = _parse_location(location)
        if origin is None:
            raise AmapError("invalid location, expected 'lon,lat'")
        return await self._place_search(
            {
                "query": keywords,
                "location": _latlng(origin["lon"], origin["lat"]),
                "radius": radius,
            },
            page=page,
            offset=offset,
        )

    async def _place_search(
        self, extra: dict[str, str | int], *, page: int = 1, offset: int = 10
    ) -> list[dict]:
        params: dict[str, str | int] = {
            "ak": self._ak,
            "output": "json",
            "scope": "2",
            "page_size": offset,
            "page_num": page - 1,
        }
        params.update(extra)
        data = await self._request_json(
            "/place/v2/search", {k: str(v) for k, v in params.items()}
        )
        results = data.get("results")
        if not isinstance(results, list):
            return []
        return [_normalize_poi(p) for p in results if isinstance(p, dict)]

    # ---------- 地理编码 ----------

    async def regeo(self, *, lon: float, lat: float) -> dict:
        """/reverse_geocoding/v3 —— 入参 GCJ-02，出参形状对齐 AmapClient。"""
        data = await self._request_json(
            "/reverse_geocoding/v3/",
            {"ak": self._ak, "output": "json", "location": _latlng(lon, lat)},
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        comp = (
            result.get("addressComponent")
            if isinstance(result.get("addressComponent"), dict)
            else {}
        )
        province = _as_str(comp.get("province"))
        return {
            "country": None,  # 百度 v3 不回 country 键
            "province": province,
            "city": _as_str(comp.get("city")) or province,
            "district": _as_str(comp.get("district")),
            "address": _as_str(result.get("formatted_address")),
        }

    async def ip_locate(self) -> dict:
        """/location/ip —— 按出口 IP 定位，形状对齐（无点坐标消费）。"""
        data = await self._request_json(
            "/location/ip", {"ak": self._ak, "output": "json"}
        )
        content = data.get("content") if isinstance(data.get("content"), dict) else {}
        detail = (
            content.get("address_detail")
            if isinstance(content.get("address_detail"), dict)
            else {}
        )
        province = _as_str(detail.get("province"))
        return {
            "province": province,
            "city": _as_str(detail.get("city")) or province,
            "adcode": _as_str(detail.get("adcode")),
        }

    # ---------- 天气 ----------

    async def get_weather(self, adcode: str, *, extensions: str = "all") -> dict:
        """/weather/v1 —— district_id 即 6 位行政区划码（GB/T 2260，
        与高德 adcode 同源）；extensions="base"→实况(now)，"all"→
        未来 5 天预报(fc，基础服务档)。返回形状与 AmapClient 一致。

        2026-10-28 实测：百度不收省级码（XX0000 →「查询的区域编码
        无效」），收市/区级；高德 CITY_ADCODES 直辖市用省级码，故入口
        归一 XX0000→XX0100（GB/T 2260 市辖区惯例码），落库仍用原始
        adcode（weather_reports 以 (source, adcode, kind) 为键，保持
        与高德体系对齐）。
        """
        district_id = (
            adcode[:-4] + "0100"
            if len(adcode) == 6 and adcode.endswith("0000")
            else adcode
        )
        data = await self._request_json(
            "/weather/v1/",
            {
                "ak": self._ak,
                "output": "json",
                "district_id": district_id,
                "data_type": "now" if extensions == "base" else "fc",
            },
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        location = (
            result.get("location") if isinstance(result.get("location"), dict) else {}
        )
        city = _as_str(location.get("city"))
        now = result.get("now")
        forecasts = result.get("forecasts")
        if extensions == "base" and isinstance(now, dict):
            return {
                "kind": "live",
                "city": city,
                "adcode": adcode,
                "report_time": None,  # 百度无发布时间字段
                "payload": {
                    "weather": _as_str(now.get("text")),
                    "temperature": _num(now.get("temp")),
                    "wind_direction": _as_str(now.get("wind_dir")),
                    "wind_power": _as_str(now.get("wind_class")),
                    "humidity": _as_str(now.get("humidity")),
                },
            }
        if extensions != "base" and isinstance(forecasts, list) and forecasts:
            casts = [
                {
                    "date": _as_str(c.get("date")),
                    "day_weather": _as_str(c.get("text_day")),
                    "night_weather": _as_str(c.get("text_night")),
                    "day_temp": _num(c.get("high")),
                    "night_temp": _num(c.get("low")),
                    "day_wind": _as_str(c.get("wd_day")),
                    "day_wind_power": _as_str(c.get("wc_day")),
                }
                for c in forecasts
                if isinstance(c, dict)
            ]
            return {
                "kind": "forecast",
                "city": city,
                "adcode": adcode,
                "report_time": None,
                "payload": {"casts": casts},
            }
        return {}

    # ---------- 路线规划 ----------

    async def walking_route(
        self,
        origin: str,
        destination: str,
        *,
        origin_id: str | None = None,
        destination_id: str | None = None,
    ) -> dict:
        """/direction/v2/walking —— 入参 'lon,lat'(GCJ-02，高德序，签名
        对齐)；origin_id/destination_id 百度无对应，收下不用。"""
        data = await self._request_json(
            "/direction/v2/walking",
            {
                "ak": self._ak,
                "output": "json",
                "origin": self._swap(origin),
                "destination": self._swap(destination),
            },
            timeout_seconds=self._route_timeout_seconds,
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        routes = result.get("routes")
        if (
            not isinstance(routes, list)
            or not routes
            or not isinstance(routes[0], dict)
        ):
            # 同起终点合法：百度可能回空 routes
            return {"distance_m": 0, "duration_s": None, "steps": [], "polyline": []}
        raw_steps = routes[0].get("steps")
        steps = (
            [_normalize_walking_step(s) for s in raw_steps if isinstance(s, dict)]
            if isinstance(raw_steps, list)
            else []
        )
        distance_m = _parse_int(routes[0].get("distance"))
        if distance_m is None:
            distance_m = sum(step["distance_m"] for step in steps)
        return {
            "distance_m": distance_m,
            "duration_s": _parse_int(routes[0].get("duration")),
            "steps": steps,
            "polyline": [point for step in steps for point in step["polyline"]],
        }

    @staticmethod
    def _swap(loc: str) -> str:
        """/'lon,lat'(GCJ-02，高德序) -> 'lat,lng'(BD-09，百度序)。"""
        point = _parse_location(loc)
        if point is None:
            raise AmapError("invalid coordinates, expected 'lon,lat'")
        return _latlng(point["lon"], point["lat"])

    async def distance(
        self, origins: list[str], destination: str, *, type_: int = 1
    ) -> list[dict]:
        """/routematrix/v2/walking（type_=1 步行；其它方式未接）。
        起点顺序返回 [{distance_m, duration_s}]。"""
        if type_ != 1:
            raise AmapError("baidu routematrix: only walking (type_=1) supported")
        data = await self._request_json(
            "/routematrix/v2/walking",
            {
                "ak": self._ak,
                "output": "json",
                "origins": "|".join(self._swap(o) for o in origins),
                "destinations": self._swap(destination),
            },
            timeout_seconds=self._route_timeout_seconds,
        )
        result = data.get("result")
        if not isinstance(result, list):
            return []
        out = []
        for row in result:
            if not isinstance(row, dict):
                continue
            distance = (
                row.get("distance") if isinstance(row.get("distance"), dict) else {}
            )
            duration = (
                row.get("duration") if isinstance(row.get("duration"), dict) else {}
            )
            out.append(
                {
                    "distance_m": _parse_int(distance.get("value")),
                    "duration_s": _parse_int(duration.get("value")),
                }
            )
        return out

    async def transit_route(
        self,
        origin: str,
        destination: str,
        *,
        city: str,
        cityd: str | None = None,
    ) -> list[dict]:
        """/direction/v2/transit —— city/cityd 收下不用（百度自动判城）。
        方案形状对齐 AmapClient：[{cost_yuan, duration_s,
        walking_distance_m, segments:[{walking?, rides?}]}]。
        """
        data = await self._request_json(
            "/direction/v2/transit",
            {
                "ak": self._ak,
                "output": "json",
                "origin": self._swap(origin),
                "destination": self._swap(destination),
            },
            timeout_seconds=self._route_timeout_seconds,
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        # 容器键名未逐字段核实：routes/transits 双候选
        plans_raw = result.get("routes")
        if not isinstance(plans_raw, list):
            plans_raw = result.get("transits")
        if not isinstance(plans_raw, list):
            return []
        plans = []
        for plan in plans_raw[:3]:
            if not isinstance(plan, dict):
                continue
            steps_raw = plan.get("steps")
            if not isinstance(steps_raw, list):
                steps_raw = plan.get("segments")
            segments, walking_m = _normalize_transit_steps(
                steps_raw if isinstance(steps_raw, list) else []
            )
            plans.append(
                {
                    "cost_yuan": _parse_float(plan.get("price"))
                    or _parse_float(plan.get("cost")),
                    "duration_s": _parse_int(plan.get("duration")),
                    "walking_distance_m": walking_m,
                    "segments": segments,
                }
            )
        return plans

    # ---------- 营业时间（enrich 用；POI 底库 amap_id 语义绑高德） ----------

    async def place_hours(self, poi_id: str) -> dict:
        """/place/v2/detail?scope=2 —— poi_id 须为百度 uid。"""
        data = await self._request_json(
            "/place/v2/detail",
            {"ak": self._ak, "output": "json", "scope": "2", "uid": poi_id},
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        detail = (
            result.get("detail_info")
            if isinstance(result.get("detail_info"), dict)
            else {}
        )
        return _hours_result(result, detail)

    async def search_hours(
        self, keyword: str, city: str | None = None, *, location: str | None = None
    ) -> dict:
        """按名称查营业时间（首条命中）；location 参数收下不用
        （百度无高德 text/around 独立配额池的降级需求）。"""
        params: dict[str, str] = {
            "ak": self._ak,
            "output": "json",
            "scope": "2",
            "query": keyword,
            "page_size": "1",
        }
        if city:
            params["region"] = city
            params["city_limit"] = "true"
        data = await self._request_json("/place/v2/search", params)
        results = data.get("results")
        poi = None
        if isinstance(results, list) and results and isinstance(results[0], dict):
            poi = results[0]
        detail = (
            poi.get("detail_info")
            if isinstance(poi, dict) and isinstance(poi.get("detail_info"), dict)
            else {}
        )
        return _hours_result(poi or {}, detail)


def _hours_result(poi: dict, detail: dict) -> dict:
    hours = next((h for h in (_as_str(detail.get(k)) for k in _HOURS_KEYS) if h), None)
    result = {
        "opening_hours": hours,
        "rating": _as_str(detail.get("overall_rating")),
        "address": _as_str(poi.get("address")),
    }
    if poi:
        result["matched"] = _as_str(poi.get("name"))
        result["poi_id"] = _as_str(poi.get("uid"))
        tel = _as_str(poi.get("telephone"))
        if tel:
            result["tel"] = tel
    return result


def _normalize_poi(poi: dict) -> dict:
    """百度 POI -> AmapClient.search_poi 同构形状（坐标已转 GCJ-02）。"""
    detail = poi.get("detail_info") if isinstance(poi.get("detail_info"), dict) else {}
    city = _as_str(poi.get("city")) or _as_str(poi.get("province"))
    point = _gcj_point(poi.get("location"))
    hours = next((h for h in (_as_str(detail.get(k)) for k in _HOURS_KEYS) if h), None)
    # 空列表不落键：回源侧 hit.get("photos") 判空即可（同 AmapClient 约定）
    normalized = {
        "source": "baidu",
        "source_poi_id": _as_str(poi.get("uid")),
        "name": _as_str(poi.get("name")),
        "city": city,
        "category": _as_str(detail.get("tag")),
        "address": _as_str(poi.get("address")),
        "location": point,
        "opening_hours": hours,
        "rating": _as_str(detail.get("overall_rating")),
        # around 模式带回直线距离（米）；text 结果无此字段
        "distance": _as_str(poi.get("distance")),
    }
    return normalized


def _normalize_walking_step(step: dict) -> dict:
    road = _as_str(step.get("road_name")) or _as_str(step.get("road"))
    return {
        "instruction": _as_str(step.get("instructions")) or "",
        "road": road,
        "distance_m": _parse_int(step.get("distance"), default=0),
        "orientation": _as_str(step.get("orientation")),
        "polyline": _gcj_polyline(step.get("path")),
    }


_RIDE_KINDS = {
    "bus": "bus",
    "subway": "railway",
    "railway": "railway",
    "train": "railway",
}


def _normalize_transit_steps(steps: list) -> tuple[list[dict], int]:
    """百度 transit 方案 steps -> 高德 segments 形状。

    连续 walking 步归并为一段 walking；乘车步（type bus/subway/…）
    归并前 flush。返回 (segments, 总步行距离米)。
    """
    segments: list[dict] = []
    walk_buf: list[dict] = []
    walk_durations: list[int | None] = []
    walking_total = 0

    def flush() -> None:
        nonlocal walk_buf, walk_durations
        if walk_buf:
            # 百度无高德 walking 容器级 duration，取步级之和（缺省步跳过）
            known = [d for d in walk_durations if d is not None]
            segments.append(
                {
                    "walking": {
                        "distance_m": sum(s["distance_m"] for s in walk_buf),
                        "duration_s": sum(known) if known else None,
                        "steps": walk_buf,
                    },
                    "rides": [],
                }
            )
            walk_buf = []
            walk_durations = []

    for step in steps:
        if not isinstance(step, dict):
            continue
        kind_raw = (_as_str(step.get("type")) or "").lower()
        if kind_raw in ("", "walking"):
            walking_total += _parse_int(step.get("distance"), default=0)
            walk_buf.append(_normalize_walking_step(step))
            walk_durations.append(_parse_int(step.get("duration")))
            continue
        flush()
        vehicle = step.get("vehicle") if isinstance(step.get("vehicle"), dict) else {}
        ride = {
            "kind": _RIDE_KINDS.get(kind_raw, "bus"),
            "name": _as_str(vehicle.get("name")) or "",
            "type": _as_str(vehicle.get("type")),
            "departure_stop": _as_str(step.get("entry")) or None,
            "arrival_stop": _as_str(step.get("exit")) or None,
            "via_stops": 0,
            "departure_time": None,
        }
        segments.append(
            {
                "walking": None,
                "rides": [ride],
            }
        )
    flush()
    return segments, walking_total
