"""地图 WebService 提供方工厂（2026-10-27 高德 5 万技术费转百度）。

`settings.map_provider == "baidu"` 时返回 BaiduClient——与 AmapClient
方法同构（鸭子类型）、共用 AmapError/AmapTimeoutError 异常体系，
API 层 except 子句与 detail 错误码（amap_timeout 等）零改动，前端
i18n 文案不动。返回类型注解写 AmapClient 仅为兼容既有引用。

批量作业走此工厂：refresh_pois（2026-10-29 用户拍板：月刷全面转百度；
链②按 provider id 命名空间过滤——高德行只在 amap 下直查；--match 骨架
升级随 provider 命名空间，百度下同权生效（2026-10-30）；hours_source 标
baidu_detail/baidu_search，amap 保旧标签 amap_v5_*）；backfill_locations
（2026-10-28 新作业，坐标补全，配额熔断异常共用）。
2026-10-28 全量收口（一键切图商）：API 平面（amap/weather/plan/navigation 代理）、
规划器注入、天气抓取（--src 缺省=map_provider）、chinatravel 导入定位、
deeplinks（provider 参数，baidumap:// 系）、前端步行外链（/api/v1/amap/provider
预取）全部走本工厂或 settings.map_provider；leg_source / hours_source 按客户端
vendor 属性标注（amap/baidu），心愿单条目定城亦走注入客户端。仍有意直连
AmapClient 的仅剩：enrich_amap_detail（作业名即高德语义）与 fetch_weather
（不走工厂但 --src 双轴自建客户端，缺省跟随 map_provider）。
"""

from __future__ import annotations

from app.config import Settings
from app.services.amap_client import AmapClient
from app.services.baidu_client import BaiduClient
from app.services.tencent_client import TencentClient


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


# ---------- 按功能的图商优先级（2026-10-30 用户拍板「按三家富裕度排」） ----------
# 个人认证档免费配额口径（2026-10-30 实测/官方页核对）：
#   检索：amap 搜索 5,000 次/月（≈166/日）> tencent 200 次/日（2025-03 调整后）
#         > baidu ~100 次/日（本仓库两次实测烧尽：10-28 补坐标、10-30 月刷后）。
#   逆地理：baidu 实测最宽裕（10-30 单日 1,300+ 次补地址零熔断）
#         > amap（共享 15 万次/月基础 LBS 池）> tencent 6,000 次/日。
#   步行路线：baidu 现役主力（长期未见配额死）> amap；tencent 无 walking_route
#         不入链。企业认证后各档 ×10~×20，届时重排本表。
# 高德另有 WAF 反爬风控（bixi punish，配额未到也可能被拦）；百度有临时并发
# 限速（非配额，退避重试即恢复）。链上任何一家配额死由调用方 latch 逐家降级。
FUNCTION_PROVIDER_PRIORITY: dict[str, tuple[str, ...]] = {
    "search": ("amap", "tencent", "baidu"),
    "regeo": ("baidu", "amap", "tencent"),
    "walking": ("baidu", "amap"),
    "transit": ("baidu", "amap"),  # 公交同 walking，tencent 无 transit_route
    # tencent 无 walking_route，不入链
}


def build_vendor(vendor: str, settings: Settings) -> AmapClient | None:
    """按 vendor 名建客户端；key 未配置返回 None（链上自动跳过）。"""
    if vendor == "amap":
        if not settings.amap_api_key:
            return None
        return AmapClient(
            key=settings.amap_api_key,
            base_url=settings.amap_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
            route_timeout_seconds=settings.amap_route_timeout_seconds,
        )
    if vendor == "baidu":
        if not settings.baidu_ak:
            return None
        return BaiduClient(
            ak=settings.baidu_ak,
            base_url=settings.baidu_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
            route_timeout_seconds=settings.amap_route_timeout_seconds,
        )
    if vendor == "tencent":
        if not settings.tencent_map_key:
            return None
        return TencentClient(
            ak=settings.tencent_map_key,
            base_url=settings.tencent_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
            route_timeout_seconds=settings.amap_route_timeout_seconds,
        )
    return None


def build_client_chain(settings: Settings, function: str) -> list[AmapClient]:
    """某功能的图商降级链：按 FUNCTION_PROVIDER_PRIORITY 排序，缺 key 跳过。"""
    chain: list[AmapClient] = []
    for vendor in FUNCTION_PROVIDER_PRIORITY.get(function, ()):
        client = build_vendor(vendor, settings)
        if client is not None:
            chain.append(client)
    return chain
