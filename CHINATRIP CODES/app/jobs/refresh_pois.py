"""POI 地址/营业时间刷新作业（CLI，v2.4.4 用户拍板；2026-10-28 起一行一月）。

节奏（2026-10-28 定稿）：作业仍每日跑（schtasks 02:00，照旧嚼积压），
但 stale 窗口 30 天（poi_details._STALE_AFTER）——**每行最多一月被
回源碰一次**，命中/未命中盖戳同权，配额烧耗较 24h 窗口降一个量级。

链序（用户拍板：携程先，高德V5后）：
  ⓪回源匹配（--match）：source!=provider 的骨架行先走图商关键词匹配
    （名称相似度 + 距离双闸，app.services.poi_backfill）——命中则
    升级 source→provider、source_poi_id→图商 ID（amap=高德 ID /
    baidu=百度 uid；2026-10-30 起百度下同权生效，不再跳过），链② 才有意义
  ①携程 sight 页（CtripHoursReader，slug 白名单 + 早停）
  ②place/detail（poi_id 直查）——仅 poi_id 属当前图商命名空间的行
    （2026-10-29 图商转百度：MAP_PROVIDER=baidu 时客户端走工厂
    BaiduClient，命名空间 source=="baidu"（uid）；高德行直查无意义）
  ③place/text 关键词搜索（首条；location 供高德 text/around 降级，
    百度收下不用）
  ④地址兜底（2026-10-30）：搜索链全空且行有坐标 → 逆地理 regeo 补门址
    （baidu 主源 → amap 兜底；regeo 与 place 检索是独立配额池，place
    熔断不影响本链继续填地址——百度 place 日配额实测仅百级）
命中即 upsert 进 pois（address/opening_hours/hours_source/hours_updated_at）；
规划端只读库（PoiDetailStore），不当场抓取。

防烧配额（2026-10-24 实测 200 连续超限）：
  quota 熔断——链②③任一遇 AmapQuotaExhaustedError(10021) 即熔断，
    本轮剩余行跳过一切高德调用（携程链照跑），跳过数计 amap_skipped
  miss 冷却——未命中行 touch hours_updated_at=now（不写 hours/source），
    30 天静默（与月度刷新节奏一致），永久缺 hours 的行不再每轮重复查询

防风控：--rotate 无 --city 时按 weekday 城轮转——库内 DISTINCT city
里第 weekday%N 个起每隔 7 取 1（一周覆盖全城、每天负载 1/7）。

用法：
    python -m app.jobs.refresh_pois [--limit 200] [--city 重庆]
        [--source chinatravel,osm] [--rotate] [--match]
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from app.config import get_settings
from app.models import Poi
from app.services.amap_client import AmapClient, AmapQuotaExhaustedError
from app.services.ctrip_hours import get_ctrip_hours
from app.services.map_provider import build_map_client, map_ready
from app.services.poi_backfill import match_and_enrich, normalize_name
from app.services.poi_details import get_poi_detail_store
from app.services.tencent_client import TencentClient

logger = logging.getLogger(__name__)


def rotate_cities(cities: list[str], weekday: int, *, span: int = 7) -> list[str]:
    """城轮转选子集（纯函数，cities/weekday 可注入测试）。

    第 weekday%N 个城市起、每隔 span 取 1 个：城市数 ≥7 时每天约 1/7
    负载、一周覆盖全城；不足 7 城时每天取 1 个循环覆盖。
    """
    n = len(cities)
    if n == 0:
        return []
    start = weekday % n
    return list(cities[start::span])


def _city_ok(row_city: str | None, city: str | None, cities: list[str] | None) -> bool:
    rc = (row_city or "").removesuffix("市")
    if city is not None and rc != (city or "").removesuffix("市"):
        return False
    if cities is not None and rc not in {(c or "").removesuffix("市") for c in cities}:
        return False
    return True


async def _match_skeletons(
    session_factory: Any,
    model: Any,
    targets: list[tuple],
    amap: Any,
    *,
    provider: str = "amap",
    fallback: Any = None,
) -> tuple[dict[tuple[str, str], tuple[str, str]], dict]:
    """--match 前置：对 source!=provider 的目标行先跑回源匹配。

    返回 (升级映射, 匹配统计)：映射键为原 (source, source_poi_id)，
    值为 (provider, 新图商 ID)——命中升级后链② place/detail 才有意义
    （amap→高德 ID；baidu→百度 uid，2026-10-30 起百度同权生效）。
    """
    upgrades: dict[tuple[str, str], tuple[str, str]] = {}
    mstats: dict = {"matched": 0, "duplicate": 0, "miss": 0, "error": 0}
    if session_factory is None:
        return upgrades, mstats
    keys = sorted(
        {(t[3] or "", t[0]) for t in targets if (t[3] or provider) != provider}
    )
    if not keys:
        return upgrades, mstats
    row_ids: dict[tuple[str, str], Any] = {}
    rows: list[Any] = []
    with session_factory() as session:
        for src, pid in keys:
            r = (
                session.query(model)
                .filter_by(source=src, source_poi_id=pid)
                .one_or_none()
            )
            if r is not None:
                rows.append(r)
                row_ids[(src, pid)] = r.id
    mstats = await match_and_enrich(
        session_factory,
        model,
        rows,
        amap,
        vendor=provider,
        fallback=fallback,
        fallback_vendor=getattr(fallback, "vendor", "amap") if fallback else "amap",
    )
    with session_factory() as session:
        for key, rid in row_ids.items():
            r = session.get(model, rid)
            if r is None or (r.source or "") != provider:
                continue
            upgrades[key] = (provider, r.source_poi_id)
    return upgrades, mstats


async def refresh_pois(
    store,
    ctrip,
    amap,
    *,
    limit: int = 200,
    city: str | None = None,
    cities: list[str] | None = None,
    sources: tuple[str, ...] | None = None,
    match: bool = False,
    session_factory: Any = None,
    provider: str = "amap",
    fallback: Any = None,
    tertiary: Any = None,
) -> dict:
    # 链② 只查当前图商命名空间的 poi_id（高德 ID vs 百度 uid）；
    # --match 升级随 provider 命名空间（map_provider 模块头同款边界）
    id_ns = provider
    detail_tag = f"{provider}_v5_detail" if provider == "amap" else f"{provider}_detail"
    search_tag = f"{provider}_v5_search" if provider == "amap" else f"{provider}_search"
    # fallback 高德兜底（2026-10-30 用户拍板「失败行回退高德」）：
    # 主源报错/无候选/无 hours 无 address 行用高德重试；amap 命名空间行
    # 在百度下不可直查 → 高德 detail 直查。高德配额尽只停兜底，百度配额
    # 尽仍整体熔断（别把高德配额整晚烧穿）。
    fb_vendor = (getattr(fallback, "vendor", "") or "") if fallback else ""
    fb_ns = fb_vendor
    fb_detail_tag = (
        f"{fb_vendor}_v5_detail" if fb_vendor == "amap" else f"{fb_vendor}_detail"
    )
    fb_search_tag = (
        f"{fb_vendor}_v5_search" if fb_vendor == "amap" else f"{fb_vendor}_search"
    )
    fb_dead = False
    # regeo 独立配额池熔断旗（主源/兜底/腾讯分开；place 熔断不波及本链）
    regeo_dead = False
    fb_regeo_dead = False
    tc_dead = False
    tc_regeo_dead = False
    targets = [
        t
        for t in store.stale_pois(limit=limit, sources=sources, city=city)
        if _city_ok(t[1], city, cities)
    ]
    stats = {
        "total": len(targets),
        "ctrip": 0,
        detail_tag: 0,
        search_tag: 0,
        "miss": 0,
        "amap_skipped": 0,
        "miss_cooldown": 0,
    }
    if fallback is not None:
        # 兜底命中计入 amap_v5_* 标签键（stats[source] += 1 需要预置键）
        stats[fb_detail_tag] = 0
        stats[fb_search_tag] = 0
    upgrades: dict[tuple[str, str], tuple[str, str]] = {}
    quota_dead = False
    if match:
        # 骨架升级随 provider 命名空间（amap/baidu 同构，2026-10-30 百度不再跳过）
        upgrades, mstats = await _match_skeletons(
            session_factory, Poi, targets, amap, provider=provider, fallback=fallback
        )
        stats["matched"] = mstats["matched"]
        stats["duplicate"] = mstats["duplicate"]
        if mstats.get("quota_exhausted"):
            # --match 阶段已烧尽配额：主循环直接进熔断态
            quota_dead = True
            stats["amap_quota_exhausted"] = True
    for poi_id, poi_city, name, poi_source, location in targets:
        upgraded = upgrades.get((poi_source or "", poi_id))
        if upgraded is not None:
            # 回源命中：骨架行已是高德 ID，链② 可直查
            poi_source, poi_id = upgraded
        hours = address = None
        source = None
        # 0009 富化字段（DESIGN §3.1/3.2）：跨链合并——携程给
        # 时长/点评数/标签/门票，高德给评分/照片/电话/商圈
        rich: dict = {}
        # ① 携程先（用户拍板 2026-10-19；不同供应商，quota 熔断不波及）
        try:
            fields = await ctrip.detail_fields_for(poi_city or "", name or "")
        except Exception:
            logger.warning(
                "refresh_pois: ctrip detail_fields_for failed, name=%s",
                name,
                exc_info=True,
            )
            fields = None
        if fields:
            hours = fields.get("opening_hours")
            if hours:
                source = "ctrip"
            rich.update(
                {
                    "suggested_duration_min": fields.get("suggested_duration_min"),
                    "duration_source": (
                        "ctrip" if fields.get("suggested_duration_min") else None
                    ),
                    "rating": fields.get("rating"),
                    "rating_source": "ctrip" if fields.get("rating") else None,
                    "rating_count": fields.get("rating_count"),
                    "review_tags": fields.get("review_tags"),
                    "review_tags_source": (
                        "ctrip" if fields.get("review_tags") else None
                    ),
                    "ticket_price_min": fields.get("ticket_price_min"),
                    "ticket_price_max": fields.get("ticket_price_max"),
                    "ticket_source": (
                        "ctrip" if fields.get("ticket_price_min") else None
                    ),
                }
            )
        # ② 图商 detail（poi_id 直查）：主源命名空间行走主源；fallback
        #    命名空间行走 fallback（百度下 amap 行也能直查补 hours/address）
        detail_which = None
        if not hours:
            if amap is not None and (poi_source or id_ns) == id_ns:
                detail_which = "main"
            elif fallback is not None and (poi_source or fb_ns) == fb_ns:
                detail_which = "fb"
        if detail_which is not None:
            client = amap if detail_which == "main" else fallback
            vendor_name = id_ns if detail_which == "main" else fb_vendor
            tag = detail_tag if detail_which == "main" else fb_detail_tag
            if detail_which == "main" and quota_dead:
                stats["amap_skipped"] += 1
            elif detail_which == "fb" and fb_dead:
                stats["fb_skipped"] = stats.get("fb_skipped", 0) + 1
            else:
                out = None
                try:
                    out = await client.place_hours(poi_id)
                except AmapQuotaExhaustedError:
                    if detail_which == "main":
                        quota_dead = True
                        stats["amap_quota_exhausted"] = True
                    else:
                        fb_dead = True  # 只停 fallback，不动主源
                except Exception:
                    logger.warning(
                        "refresh_pois: %s place_hours failed, name=%s poi_id=%s",
                        vendor_name,
                        name,
                        poi_id,
                        exc_info=True,
                    )
                if isinstance(out, dict):
                    hours = out.get("opening_hours")
                    address = out.get("address")
                    if hours:
                        source = tag
                    if out.get("rating"):
                        rich.update(
                            {"rating": out["rating"], "rating_source": vendor_name}
                        )
                    rich.update(
                        {
                            k: v
                            for k, v in (
                                ("photos", out.get("photos")),
                                ("phone", out.get("tel")),
                                ("business_area", out.get("business_area")),
                            )
                            if v
                        }
                    )
        # ③ 图商关键词搜索（最终兜底；location 供高德 10021 降级 around）
        if not hours and amap is not None:
            if quota_dead:
                stats["amap_skipped"] += 1
            else:
                out = None
                try:
                    out = await amap.search_hours(
                        name or "", poi_city or None, location=location
                    )
                except AmapQuotaExhaustedError:
                    quota_dead = True
                    stats["amap_quota_exhausted"] = True
                except Exception:
                    logger.warning(
                        "refresh_pois: %s search_hours failed, name=%s city=%s",
                        id_ns,
                        name,
                        poi_city,
                        exc_info=True,
                    )
                if isinstance(out, dict):
                    hours = out.get("opening_hours")
                    address = address or out.get("address")
                    if hours:
                        source = search_tag
                    if out.get("rating") and not rich.get("rating"):
                        rich.update({"rating": out["rating"], "rating_source": id_ns})
                    rich.update(
                        {
                            k: v
                            for k, v in (
                                ("photos", out.get("photos")),
                                ("phone", out.get("tel")),
                                ("business_area", out.get("business_area")),
                            )
                            if v and not rich.get(k)
                        }
                    )
        # ③b 失败行回退高德（2026-10-30 用户拍板）：主源既没给 hours 也没给
        #    address 时，高德同查询再试一次；hours_source 标 amap_v5_search
        if (
            not hours
            and not address
            and fallback is not None
            and not fb_dead
            and not quota_dead
        ):
            out = None
            try:
                out = await fallback.search_hours(
                    name or "", poi_city or None, location=location
                )
            except AmapQuotaExhaustedError:
                fb_dead = True
                stats["fb_quota_exhausted"] = True
            except Exception:
                logger.warning(
                    "refresh_pois: fallback search_hours failed, name=%s city=%s",
                    name,
                    poi_city,
                    exc_info=True,
                )
            if isinstance(out, dict):
                hours = out.get("opening_hours")
                address = address or out.get("address")
                if hours:
                    source = fb_search_tag
                if out.get("rating") and not rich.get("rating"):
                    rich.update({"rating": out["rating"], "rating_source": fb_vendor})
                rich.update(
                    {
                        k: v
                        for k, v in (
                            ("photos", out.get("photos")),
                            ("phone", out.get("tel")),
                            ("business_area", out.get("business_area")),
                        )
                        if v and not rich.get(k)
                    }
                )
        found_loc: tuple[float, float] | None = None
        found_city: str | None = None
        # ④ 地址兜底（2026-10-30）：搜索链全空且行有坐标 → 逆地理 regeo
        #    （formatted_address 即门址）。regeo 与 place 检索是独立配额
        #    池——place 熔断（百度日配额百级实测）不影响本链继续填地址；
        #    主源 regeo 尽 → 高德 regeo 兜底（用户拍板：失败行回退高德）。
        if not address and location:
            try:
                lon_s, lat_s = str(location).split(",")
                regeo_lonlat = (float(lon_s), float(lat_s))
            except ValueError:
                regeo_lonlat = None
            rg_out = None
            if regeo_lonlat is not None:
                if amap is not None and not regeo_dead:
                    try:
                        rg_out = await amap.regeo(
                            lon=regeo_lonlat[0], lat=regeo_lonlat[1]
                        )
                    except AmapQuotaExhaustedError:
                        regeo_dead = True
                    except Exception:
                        # 百度「当前并发量已超…限制访问」是临时限速非日配额
                        # （2026-10-30 实测：暂停片刻即恢复）——退避 1.5s 重试
                        # 一次再放弃，别把限速行错标成永久 miss
                        await asyncio.sleep(1.5)
                        try:
                            rg_out = await amap.regeo(
                                lon=regeo_lonlat[0], lat=regeo_lonlat[1]
                            )
                        except Exception:
                            logger.warning(
                                "refresh_pois: %s regeo failed, name=%s",
                                id_ns,
                                name,
                                exc_info=True,
                            )
                if (
                    not (isinstance(rg_out, dict) and rg_out.get("address"))
                    and fallback is not None
                    and not fb_regeo_dead
                ):
                    try:
                        rg_out = await fallback.regeo(
                            lon=regeo_lonlat[0], lat=regeo_lonlat[1]
                        )
                    except AmapQuotaExhaustedError:
                        fb_regeo_dead = True
                    except Exception:
                        logger.warning(
                            "refresh_pois: fallback regeo failed, name=%s",
                            name,
                            exc_info=True,
                        )
                if (
                    not (isinstance(rg_out, dict) and rg_out.get("address"))
                    and tertiary is not None
                    and not tc_regeo_dead
                ):
                    try:
                        rg_out = await tertiary.regeo(
                            lon=regeo_lonlat[0], lat=regeo_lonlat[1]
                        )
                    except AmapQuotaExhaustedError:
                        tc_regeo_dead = True
                    except Exception:
                        logger.warning(
                            "refresh_pois: tencent regeo failed, name=%s",
                            name,
                            exc_info=True,
                        )
            if isinstance(rg_out, dict):
                address = address or rg_out.get("address")
                if (poi_city or "") == "" and rg_out.get("city"):
                    # 逆地理顺带补缺失城市（百度/高德 regeo 归一里都带 city）
                    found_city = rg_out.get("city")
                if address:
                    stats["regeo_addr"] = stats.get("regeo_addr", 0) + 1
        # ④b 无城市且无坐标行（2026-10-30 用户拍板「44 行连城市都没有的补上」）：
        #    腾讯正地理编码（address=名称，无需城市入参）→ 补 city + GCJ-02
        #    坐标；title 与行名互含才采信（同 ④c 闸，宁缺勿错）。city 补上后
        #    本行即刻走 ④c 按名搜地址。
        if (
            (poi_city or "") == ""
            and not location
            and not address
            and tertiary is not None
            and not tc_dead
        ):
            try:
                geo = await tertiary.geocode(name or "")
            except AmapQuotaExhaustedError:
                tc_dead = True
            except Exception:
                logger.warning(
                    "refresh_pois: tencent geocode failed, name=%s", name, exc_info=True
                )
            else:
                geo_title = normalize_name(geo.get("title") or "")
                row_norm0 = normalize_name(name or "")
                if (
                    geo.get("lon") is not None
                    and geo_title
                    and min(len(geo_title), len(row_norm0)) >= 3
                    and (geo_title in row_norm0 or row_norm0 in geo_title)
                ):
                    found_city = geo.get("city")
                    found_loc = (geo["lon"], geo["lat"])
                    stats["tencent_city"] = stats.get("tencent_city", 0) + 1
        if found_city and (poi_city or "") == "":
            poi_city = found_city
        # ④c 无坐标行（2026-10-30 用户供腾讯 key）：按名地点搜索补地址，
        #    包含关系闸（归一化后互含、短侧≥3字，防泛称误配）——这些行
        #    没有「距离闸」可守，用更严的名字闸替代；命中顺带回填 GCJ-02
        #    坐标，行此后即可参与距离闸升级。个人 key 无城市搜不了（121），
        #    空城行经 ④b 补城市后即可进本段。
        if not address and not location and tertiary is not None and not tc_dead:
            try:
                tc_cands = await tertiary.search_poi(name or "", city=poi_city or None)
            except AmapQuotaExhaustedError:
                tc_dead = True
            except Exception:
                logger.warning(
                    "refresh_pois: tencent search failed, name=%s", name, exc_info=True
                )
            else:
                row_norm = normalize_name(name or "")
                for cand in tc_cands:
                    if not isinstance(cand, dict):
                        continue
                    cand_norm = normalize_name(cand.get("name") or "")
                    if min(len(cand_norm), len(row_norm)) < 3:
                        continue
                    if cand_norm not in row_norm and row_norm not in cand_norm:
                        continue
                    address = cand.get("address")
                    cloc = cand.get("location") or {}
                    if cloc:
                        found_loc = (cloc["lon"], cloc["lat"])
                    break
                if address:
                    stats["tencent_addr"] = stats.get("tencent_addr", 0) + 1
        if hours:
            # source=poi_source：按行自身命名空间原位更新——缺省 "amap"
            # 会在骨架行（chinatravel/5a/unesco/show）上查无此行 → 新建
            # 幽灵重复行（2026-10-30 实锤：+46 行 amap 壳、原行仍无地址）；
            # location=found_loc：④b/④c 回填的坐标随地址一起落库
            store.upsert(
                poi_id,
                city=poi_city,
                name=name,
                address=address,
                opening_hours=hours,
                hours_source=source,
                source=poi_source,
                location=found_loc,
                **{k: v for k, v in rich.items() if v is not None},
            )
            stats[source] += 1
        elif any(v is not None and v for v in rich.values()):
            # 小时未命中但富化字段有值（携程页面无开放时间块）——也别丢
            # （source=poi_source 原位更新，同上防幽灵行）
            store.upsert(
                poi_id,
                city=poi_city,
                name=name,
                address=address,
                source=poi_source,
                location=found_loc,
                **{k: v for k, v in rich.items() if v is not None},
            )
            stats["enrich_only"] = stats.get("enrich_only", 0) + 1
            store.touch_hours_checked(poi_id)
        elif address:
            # hours 未命中但地址已到手（开放型点位常见）——地址先落库，
            # 别跟 hours 一起丢；仍盖冷却戳防下轮重复烧配额
            store.upsert(
                poi_id,
                city=poi_city,
                name=name,
                address=address,
                source=poi_source,
                location=found_loc,
            )
            store.touch_hours_checked(poi_id)
            stats["address_only"] = stats.get("address_only", 0) + 1
        else:
            stats["miss"] += 1
            # miss 冷却：盖戳进 24h 静默，别下轮再烧 text 配额
            store.touch_hours_checked(poi_id)
            stats["miss_cooldown"] += 1
    return stats


def _distinct_cities(session_factory: Any) -> list[str]:
    """库内 DISTINCT city（去「市」后缀、排序）——轮转候选。"""
    if session_factory is None:
        return []
    try:
        with session_factory() as session:
            rows = session.query(Poi.city).distinct().all()
    except Exception:
        logger.warning("refresh_pois: distinct cities failed", exc_info=True)
        return []
    return sorted({(r[0] or "").removesuffix("市") for r in rows if r[0]})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="刷新 POI 地址/营业时间（携程先→高德V5，落库 pois）"
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--city", help="只刷指定城市（如 重庆）")
    parser.add_argument(
        "--source",
        help="只刷指定来源，逗号分隔（如 chinatravel,osm）；缺省=全量",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="无 --city 时按 weekday 城轮转（每天 1/7 城市负载，防风控）",
    )
    parser.add_argument(
        "--match",
        action="store_true",
        help="回源校验：source!=当前图商 的骨架行先匹配升级（amap/baidu），再补 hours",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    store = get_poi_detail_store()
    if not store.ping():
        print(
            json.dumps(
                {
                    "error": "database unreachable — "
                    "start docker db (docker compose up -d db) "
                    "or check database_url"
                },
                ensure_ascii=True,
            )
        )
        return 1
    from app.db import get_session_factory

    try:
        session_factory = get_session_factory()
    except Exception:
        session_factory = None
    # 2026-10-29 用户拍板：图商全面转百度——月刷不再直连高德，走工厂
    # （MAP_PROVIDER=baidu 时为 BaiduClient，方法同构、异常体系共用）。
    client = build_map_client(settings) if map_ready(settings) else None
    # 2026-10-30 用户拍板「失败行回退高德」：主源为百度时，高德客户端作
    # 逐行兜底；主源本身是高德时不重复建。
    fallback = None
    if client is not None and settings.map_provider != "amap" and settings.amap_api_key:
        fallback = AmapClient(
            key=settings.amap_api_key,
            base_url=settings.amap_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
            route_timeout_seconds=settings.amap_route_timeout_seconds,
        )
    # 腾讯第三兜底（2026-10-30 用户供 key）：坐标行 regeo 第三层 + 无城市
    # 行正地理编码补 city/坐标 + 无坐标行按名搜地址；独立配额池。
    tertiary = None
    if settings.tencent_map_key:
        tertiary = TencentClient(
            ak=settings.tencent_map_key,
            base_url=settings.tencent_base_url,
            timeout_seconds=settings.amap_timeout_seconds,
        )
    sources = (
        tuple(s.strip() for s in args.source.split(",") if s.strip())
        if args.source
        else None
    )
    cities = None
    if args.rotate and not args.city:
        cities = _distinct_cities(session_factory)
    stats = asyncio.run(
        refresh_pois(
            store,
            get_ctrip_hours(),
            client,
            limit=args.limit,
            city=args.city,
            cities=cities,
            sources=sources,
            match=args.match,
            session_factory=session_factory,
            provider=settings.map_provider,
            fallback=fallback,
            tertiary=tertiary,
        )
    )
    if cities is not None:
        stats["rotated_cities"] = cities
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
