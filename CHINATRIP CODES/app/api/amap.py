import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings, get_settings
from app.services.amap_client import AmapClient, AmapError, AmapTimeoutError
from app.services.map_provider import (
    build_client_chain,
    build_map_client,
    map_ready,
)
from app.services.vendor_chain import run_vendor_chain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/amap", tags=["amap"])


def get_amap_client(settings: Settings = Depends(get_settings)) -> AmapClient:
    """按 settings.map_provider 分流（baidu 时返回方法同构的 BaiduClient，
    共用 AmapError 异常体系——返回注解写 AmapClient 仅为类型兼容）。"""
    return build_map_client(settings)


_SEARCH_LATCH: dict[str, str] = {}
_REGEO_LATCH: dict[str, str] = {}


def get_search_chain(settings: Settings = Depends(get_settings)) -> list[AmapClient]:
    """检索链 search=amap>tencent>baidu（导航页/规划页目的地搜索）。"""
    return build_client_chain(settings, "search")


def get_regeo_chain(settings: Settings = Depends(get_settings)) -> list[AmapClient]:
    """逆地理链 regeo=baidu>amap>tencent。"""
    return build_client_chain(settings, "regeo")


@router.get("/provider")
async def map_provider_info(settings: Settings = Depends(get_settings)) -> dict:
    """当前图商与就绪态（2026-10-28 一键切图商）。

    前端步行/路线外链按 provider 组装；key 永不出服务端（铁律 22 同源）。
    """
    return {"provider": settings.map_provider, "ready": map_ready(settings)}


@router.get("/poi/search")
async def search_poi(
    keywords: str = Query(min_length=1, max_length=64),
    city: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    chain: list[AmapClient] = Depends(get_search_chain),
) -> dict:
    if not map_ready(settings) or not chain:
        raise HTTPException(status_code=503, detail="amap_not_configured")
    result = await run_vendor_chain(
        chain,
        lambda c: c.search_poi(keywords, city=city, page=page),
        latch=_SEARCH_LATCH,
        function="search",
    )
    if isinstance(result, AmapTimeoutError):
        raise HTTPException(status_code=504, detail="amap_timeout") from result
    if result is None or isinstance(result, Exception):
        logger.warning("poi/search all vendors failed: %s", result)
        raise HTTPException(status_code=502, detail="amap_error") from result
    return {"items": result, "page": page}


@router.get("/regeo")
async def regeo(
    lon: float = Query(ge=-180.0, le=180.0),
    lat: float = Query(ge=-90.0, le=90.0),
    settings: Settings = Depends(get_settings),
    chain: list[AmapClient] = Depends(get_regeo_chain),
) -> dict:
    if not map_ready(settings) or not chain:
        raise HTTPException(status_code=503, detail="amap_not_configured")
    result = await run_vendor_chain(
        chain,
        lambda c: c.regeo(lon=lon, lat=lat),
        latch=_REGEO_LATCH,
        function="regeo",
    )
    if isinstance(result, AmapTimeoutError):
        raise HTTPException(status_code=504, detail="amap_timeout") from result
    if result is None or isinstance(result, Exception):
        logger.warning("regeo all vendors failed: %s", result)
        raise HTTPException(status_code=502, detail="amap_error") from result
    return result


@router.get("/ip")
async def ip_locate(
    settings: Settings = Depends(get_settings),
    client: AmapClient = Depends(get_amap_client),
) -> dict:
    if not map_ready(settings):
        raise HTTPException(status_code=503, detail="amap_not_configured")
    try:
        info = await client.ip_locate()
    except AmapTimeoutError:
        raise HTTPException(status_code=504, detail="amap_timeout") from None
    except AmapError as exc:
        logger.warning("amap error: infocode=%s info=%s", exc.infocode, exc)
        raise HTTPException(status_code=502, detail="amap_error") from exc
    return info
