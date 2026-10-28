"""地图 WebService 提供方工厂（2026-10-27 高德 5 万技术费转百度）。

`settings.map_provider == "baidu"` 时返回 BaiduClient——与 AmapClient
方法同构（鸭子类型）、共用 AmapError/AmapTimeoutError 异常体系，
API 层 except 子句与 detail 错误码（amap_timeout 等）零改动，前端
i18n 文案不动。返回类型注解写 AmapClient 仅为兼容既有引用。

批量作业（refresh_pois / enrich_amap_detail）刻意不走此工厂：POI
底库 source/amap_id 列语义绑定高德，作业仍直连 AmapClient；高德
key 真失效时它们是下一片迁移（届时 BaiduClient.uid → source_poi_id）。
"""

from __future__ import annotations

from app.config import Settings
from app.services.amap_client import AmapClient
from app.services.baidu_client import BaiduClient


def map_ready(settings: Settings) -> bool:
    if settings.map_provider == "baidu":
        return bool(settings.baidu_ak)
    return bool(settings.amap_api_key)


def build_map_client(settings: Settings) -> AmapClient:
    if settings.map_provider == "baidu":
        return BaiduClient(
            ak=settings.baidu_ak,
            base_url=settings.baidu_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
            route_timeout_seconds=settings.amap_route_timeout_seconds,
        )
    return AmapClient(
        key=settings.amap_api_key,
        base_url=settings.amap_base_url,
        timeout_seconds=settings.amap_timeout_seconds,
        route_timeout_seconds=settings.amap_route_timeout_seconds,
    )
