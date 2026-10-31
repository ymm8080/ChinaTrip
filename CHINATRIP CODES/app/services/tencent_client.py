"""腾讯位置服务 WebService 客户端——refresh_pois 链④ 第三兜底专用。

2026-10-30 用户供 key：百度/高德之外再添一个独立配额池。**有意不进
map_provider 工厂**（deeplinks/规划/天气仍走 amap|baidu 双轴），本客
户端只被 refresh_pois 用于：
  - 坐标行 regeo 第三层（formatted address 补地址）；
  - 无坐标行按名地点搜索补地址（包含关系闸，宁缺勿错），顺带回填
    GCJ-02 坐标——这些行补了坐标以后即可走距离闸升级。

约定（与 AmapClient/BaiduClient 同构的鸭子类型）：
- 异常复用 AmapError/AmapTimeoutError/AmapQuotaExhaustedError；腾讯
  status：0 成功；120/121=日调用量尽 → Quota 系；其余（含秒级限频）
  → AmapError。
- 坐标：腾讯收发 GCJ-02 且参数序是 "lat,lng"（与百度相同、与高德相
  反）；库存即 GCJ-02 → 无换算，只调序。返回统一 {"lon","lat"}。
- 个人认证配额：地点搜索/逆地理各约 1 万次/日；`region(全国)` 级别
  搜索个人 key 不可用（实测返回 121）——无城市行按名搜索直接空手
  返回，不烧配额。
"""

import logging

import httpx

from app.services.amap_client import (
    AmapError,
    AmapQuotaExhaustedError,
    AmapTimeoutError,
    _as_str,
)

logger = logging.getLogger(__name__)


class TencentClient:
    vendor = "tencent"

    def __init__(
        self,
        *,
        ak: str,
        base_url: str = "https://apis.map.qq.com",
        timeout_seconds: float = 5.0,
        route_timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._ak = ak
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._route_timeout_seconds = route_timeout_seconds or timeout_seconds
        self._transport = transport

    async def _request_json(self, path: str, params: dict[str, str]) -> dict:
        clean = {k: str(v) for k, v in params.items() if v not in (None, "")}
        clean["key"] = self._ak
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as http:
            try:
                response = await http.get(path, params=clean)
            except httpx.TimeoutException as exc:
                raise AmapTimeoutError("tencent request timed out") from exc
            except httpx.RequestError as exc:
                raise AmapError(f"tencent network error: {type(exc).__name__}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise AmapError("tencent returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise AmapError("tencent returned unexpected JSON shape")
        status = data.get("status")
        if status != 0 and status != "0":
            message = _as_str(data.get("message")) or "tencent request failed"
            if str(status) in ("120", "121"):
                raise AmapQuotaExhaustedError(message, str(status))
            raise AmapError(message, str(status))
        return data

    async def search_poi(
        self, keywords: str, *, city: str | None = None, page: int = 1
    ) -> list[dict]:
        """/ws/place/v1/search region 模式——个人 key 不支持 region(全国)，
        无 city 时直接空手返回（调用方按 miss 处理，别烧配额）。"""
        if not city:
            return []
        data = await self._request_json(
            "/ws/place/v1/search",
            {
                "keyword": keywords,
                "boundary": f"region({city},0)",
                "page_size": "10",
                "page_index": str(page),
            },
        )
        items = data.get("data")
        if not isinstance(items, list):
            return []
        return [_normalize_poi(p) for p in items if isinstance(p, dict)]

    async def geocode(self, address: str) -> dict:
        """/ws/geocoder/v1 正地理编码（address=名称，无需城市入参）。

        POI 级解析才回 title；区县级粗解 title 为空 → 调用方按闸拒绝
        （宁缺勿错）。坐标出参 GCJ-02（腾讯原样），返回 {"lon","lat"}。
        """
        data = await self._request_json("/ws/geocoder/v1", {"address": address})
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        comp = (
            result.get("address_components")
            if isinstance(result.get("address_components"), dict)
            else {}
        )
        province = _as_str(comp.get("province"))
        point = (
            result.get("location") if isinstance(result.get("location"), dict) else {}
        )
        try:
            lon = float(point.get("lng"))
            lat = float(point.get("lat"))
        except (TypeError, ValueError):
            lon = lat = None
        return {
            "province": province,
            "city": _as_str(comp.get("city")) or province,
            "district": _as_str(comp.get("district")),
            "title": _as_str(result.get("title")),
            "lon": lon,
            "lat": lat,
        }

    async def regeo(self, *, lon: float, lat: float) -> dict:
        """/ws/geocoder/v1 逆地理——入参 GCJ-02，出参形状对齐；
        formatted_addresses.recommend 比 address 更贴近门址，优先。"""
        data = await self._request_json(
            "/ws/geocoder/v1", {"location": f"{lat:.6f},{lon:.6f}"}
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        formatted = (
            result.get("formatted_addresses")
            if isinstance(result.get("formatted_addresses"), dict)
            else {}
        )
        address = (
            _as_str(formatted.get("recommend"))
            or _as_str(formatted.get("rough"))
            or _as_str(result.get("address"))
        )
        return {"address": address}

    async def place_hours(self, poi_id: str) -> dict:
        raise AmapError("tencent client: place_hours not supported")

    async def search_hours(
        self, keyword: str, city: str | None = None, *, location: str | None = None
    ) -> dict:
        """形状对齐（腾讯不供营业时间）；搜索首条地址供兜底用。"""
        cands = await self.search_poi(keyword, city=city)
        if not cands:
            return {"opening_hours": None, "address": None}
        return {"opening_hours": None, "address": cands[0].get("address")}


def _normalize_poi(poi: dict) -> dict:
    """腾讯 POI -> 同构形状（坐标已是 GCJ-02，只调 {lon,lat} 序）。"""
    point = poi.get("location") if isinstance(poi.get("location"), dict) else {}
    try:
        location = {"lon": float(point.get("lng")), "lat": float(point.get("lat"))}
    except (TypeError, ValueError):
        location = None
    return {
        "source": "tencent",
        "source_poi_id": _as_str(poi.get("id")),
        "name": _as_str(poi.get("title")),
        "address": _as_str(poi.get("address")),
        "location": location,
    }
