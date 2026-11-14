"""心愿行建行即从 POIS 底库带出点位属性（2026-11-13 用户拍板）。

「category, duration, must_visit, tier, location comes from pois during its
creation」——建行当口按名称（+城市）查底库同名 active 行，带出：

* category → kind
* suggested_duration_min → duration_minutes
* tier / site_rank（名录档：unesco/5A/国际站…，hit_tier / catalog_rank）
* location → latitude / longitude
* rain_ok（POIS 的室内/露天属性；天气本身每日刷新，不入库）

**排期日期与时刻不在这里**：那来自真实行程（plan 里该站的 start/end），
由规划器在排期时回写。

底库不可用/无同名行 → 返回 {}，建行照常（属性留空，排期时仍可用）。
"""

from sqlalchemy import text

from app.db import get_session_factory
from app.services.poi_details import hit_tier
from app.services.source_tier import catalog_rank

_CITY_SUFFIX = "市"


def _city_names(city: str | None) -> list[str]:
    c = (city or "").strip()
    if not c:
        return []
    return sorted({c, c + _CITY_SUFFIX, c.removesuffix(_CITY_SUFFIX)} - {""})


def seed_from_pois(name: str, city: str | None = None) -> dict:
    """按名称（同城优先）取 POIS 行属性；失败返回 {}，绝不抛。"""
    probe = (name or "").strip()
    if not probe:
        return {}
    names = _city_names(city)
    sql = (
        "SELECT category, suggested_duration_min, tags, source, rain_ok,"
        " ST_X(location::geometry) AS lon, ST_Y(location::geometry) AS lat"
        " FROM pois"
        " WHERE name_zh = :name AND (status IS NULL OR status = 'active')"
    )
    params: dict = {"name": probe}
    if names:
        sql += " AND city = ANY(:cities)"
        params["cities"] = names
    sql += " ORDER BY updated_at DESC LIMIT 1"
    try:
        with get_session_factory()() as session:
            row = session.execute(text(sql), params).first()
    except Exception:
        return {}
    if row is None:
        return {}
    category, duration, tags, source, rain_ok, lon, lat = row
    hit = {"name": probe, "source": source, "tags": tags or []}
    return {
        "kind": (category or None),
        "duration_minutes": duration,
        "tier": hit_tier(hit, []),
        "site_rank": catalog_rank(source, tags or []),
        "latitude": float(lat) if lat is not None else None,
        "longitude": float(lon) if lon is not None else None,
        "rain_ok": (rain_ok or None),
    }
