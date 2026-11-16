"""心愿行建行即从 POIS 底库带出点位属性（2026-11-13 用户拍板）。

「category, duration, must_visit, tier, location comes from pois during its
creation」——建行当口按名称（+城市）查底库同名 active 行，带出：

* category → kind
* suggested_duration_min → duration_minutes
* tier / site_rank（名录档：unesco/5A/国际站…，hit_tier / catalog_rank）
* location → latitude / longitude
* address → address（2026-11-16 朱家角案：心愿行卡面要带地址）
* source_poi_id → poi_id（挂回底库行，后续换点/详情/接驳都靠它）
* rain_ok（POIS 的室内/露天属性；天气本身每日刷新，不入库）

**排期日期与时刻不在这里**：那来自真实行程（plan 里该站的 start/end），
由规划器在排期时回写。

底库不可用/无同名行 → 返回 {}，建行照常（属性留空，排期时仍可用）。

同名多行（朱家角古镇 ctrip 骨架 vs 朱家角镇 histown）：**有坐标的行优先**，
其次最近更新——旧版纯按 updated_at 取，最年轻的那行恰是没坐标的 ctrip 骨架，
坐标/地址全丢（2026-11-16 用户报「朱家角没有地址和交通」）。精确同名没有再
按地名内核包含匹配（朱家角 → 朱家角古镇/朱家角镇）。
"""

from sqlalchemy import text

from app.db import get_session_factory
from app.services.poi_details import hit_tier
from app.services.poi_ingest import place_core
from app.services.source_tier import catalog_rank

_CITY_SUFFIX = "市"

#: 泛名包含匹配时不带出住宿/餐饮行（朱家角一圈民宿，不是景点本体）。
_SERVICE_CATEGORIES = ("hotel", "food", "transport", "service")


def _city_names(city: str | None) -> list[str]:
    c = (city or "").strip()
    if not c:
        return []
    return sorted({c, c + _CITY_SUFFIX, c.removesuffix(_CITY_SUFFIX)} - {""})


def _fetch(
    session,
    where: str,
    params: dict,
    city_names: list[str],
) -> list:
    sql = (
        "SELECT name_zh, category, suggested_duration_min, tags, source, rain_ok,"
        " address, source_poi_id, updated_at,"
        " ST_X(location::geometry) AS lon, ST_Y(location::geometry) AS lat"
        " FROM pois"
        f" WHERE {where} AND (status IS NULL OR status = 'active')"
    )
    if city_names:
        sql += " AND city = ANY(:cities)"
        params = {**params, "cities": city_names}
    sql += " LIMIT 50"
    return list(session.execute(text(sql), params).all())


def _rank(row) -> tuple:
    """有坐标 > 有地址 > 最近更新（同名多行取「信息最全」的那行）。"""
    _name, _cat, _dur, _tags, _src, _rain, address, _spid, updated, lon, lat = row
    return (
        1 if lon is not None and lat is not None else 0,
        1 if (address or "").strip() else 0,
        updated.timestamp() if updated is not None else 0.0,
    )


def seed_from_pois(name: str, city: str | None = None) -> dict:
    """按名称（同城优先）取 POIS 行属性；失败返回 {}，绝不抛。"""
    probe = (name or "").strip()
    if not probe:
        return {}
    names = _city_names(city)
    try:
        with get_session_factory()() as session:
            rows = _fetch(session, "name_zh = :name", {"name": probe}, names)
            if not rows:
                core = place_core(probe)
                # 内核包含回退只认「地名内核完全相等」且内核 ≥2 字（2026-11-16：
                # 宽松 LIKE 会把短名心愿吃成不相干的行——「b」命中名字含 b 的行，
                # poi_id 相同的两条愿望还会在建行去重时并成一条）。
                if not core or len(core) < 2:
                    return {}
                rows = [
                    r
                    for r in _fetch(
                        session, "name_zh LIKE :like", {"like": f"%{core}%"}, names
                    )
                    if place_core(r[0]) == core
                ]
                if len(rows) > 1:
                    rows = [
                        r for r in rows if (r[1] or "") not in _SERVICE_CATEGORIES
                    ] or rows
            if not rows:
                return {}
            row = max(rows, key=_rank)
    except Exception:
        return {}
    (
        hit_name,
        category,
        duration,
        tags,
        source,
        rain_ok,
        address,
        source_poi_id,
        _updated,
        lon,
        lat,
    ) = row
    hit = {"name": probe, "source": source, "tags": tags or []}
    return {
        "name": (hit_name or probe),
        "kind": (category or None),
        "duration_minutes": duration,
        "tier": hit_tier(hit, []),
        "site_rank": catalog_rank(source, tags or []),
        "latitude": float(lat) if lat is not None else None,
        "longitude": float(lon) if lon is not None else None,
        "address": address,
        "poi_id": source_poi_id,
        "rain_ok": (rain_ok or None),
    }
