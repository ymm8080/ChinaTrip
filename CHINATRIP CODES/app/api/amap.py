import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings, get_settings
from app.services.amap_client import AmapClient, AmapError, AmapTimeoutError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/amap", tags=["amap"])


def get_amap_client(settings: Settings = Depends(get_settings)) -> AmapClient:
    return AmapClient(
        key=settings.amap_api_key,
        base_url=settings.amap_base_url,
        timeout_seconds=settings.amap_timeout_seconds,
    )


@router.get("/poi/search")
async def search_poi(
    keywords: str = Query(min_length=1, max_length=64),
    city: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    client: AmapClient = Depends(get_amap_client),
) -> dict:
    if settings.amap_api_key == "":
        raise HTTPException(status_code=503, detail="amap_not_configured")
    try:
        items = await client.search_poi(keywords, city=city, page=page)
    except AmapTimeoutError:
        raise HTTPException(status_code=504, detail="amap_timeout") from None
    except AmapError as exc:
        logger.warning("amap error: infocode=%s info=%s", exc.infocode, exc)
        raise HTTPException(status_code=502, detail="amap_error") from exc
    return {"items": items, "page": page}


@router.get("/regeo")
async def regeo(
    lon: float = Query(ge=-180.0, le=180.0),
    lat: float = Query(ge=-90.0, le=90.0),
    settings: Settings = Depends(get_settings),
    client: AmapClient = Depends(get_amap_client),
) -> dict:
    if settings.amap_api_key == "":
        raise HTTPException(status_code=503, detail="amap_not_configured")
    try:
        info = await client.regeo(lon=lon, lat=lat)
    except AmapTimeoutError:
        raise HTTPException(status_code=504, detail="amap_timeout") from None
    except AmapError as exc:
        logger.warning("amap error: infocode=%s info=%s", exc.infocode, exc)
        raise HTTPException(status_code=502, detail="amap_error") from exc
    return info


@router.get("/ip")
async def ip_locate(
    settings: Settings = Depends(get_settings),
    client: AmapClient = Depends(get_amap_client),
) -> dict:
    if settings.amap_api_key == "":
        raise HTTPException(status_code=503, detail="amap_not_configured")
    try:
        info = await client.ip_locate()
    except AmapTimeoutError:
        raise HTTPException(status_code=504, detail="amap_timeout") from None
    except AmapError as exc:
        logger.warning("amap error: infocode=%s info=%s", exc.infocode, exc)
        raise HTTPException(status_code=502, detail="amap_error") from exc
    return info
