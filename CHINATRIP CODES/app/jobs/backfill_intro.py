"""POI 简介+图片回填作业（免费开放源：Wikidata + 中文维基百科，季更频率）。

链路（用户拍板 2026-10-23，不引商业 API）：
  ①Wikidata wbsearchentities(language=zh) 找实体 id
  ②Special:EntityData/{id}.json 取 claims：P18 图片文件名 → Wikimedia
    Commons Special:FilePath 外链（?width=800，只存外链不下载）
  ③zh.wikipedia REST summary 取 extract（>30 字才用）做简介

铁律：只填空字段——intro/intro_source、photos/photos_source 已有值绝不
覆盖。intro_source 统一标 "wikidata" 方便按源统计（值实为 zh.wikipedia
summary 的 extract，见 _backfill_row 注释）；photos 条目格式
[{"url", "source", "license"}]，license 简化写 "CC"（Commons 外链服务
自带署名跳转）。

限速：串行 + 每请求间 sleep 0.5s（礼貌抓取，Wikimedia UA 政策）。
User-Agent: "ChinaTrip-POI-library/0.1 (contact: dev@chinatrip.local)"。

注：--with-amap-photos 目前是预留空开关（no-op）——AmapClient 现有方法
均不透出 photos 数组（v3 search_poi 经 _normalize_poi 丢弃 photos，v5
search_hours/place_hours 只回 business 字段），高德 photos 兜底待
AmapClient 增加返回 photos 的方法后再接；不改 amap_client.py。
因此本 job 全程同步 httpx，无需 asyncio。

用法：
    python -m app.jobs.backfill_intro [--limit 100] [--city 重庆] [--with-amap-photos]
"""

import argparse
import json
import sys
import time
from urllib.parse import quote

import httpx
from sqlalchemy import or_

from app.db import get_session_factory
from app.models import Poi

USER_AGENT = "ChinaTrip-POI-library/0.1 (contact: dev@chinatrip.local)"
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_REQUEST_GAP_SECONDS = 0.5
# extract 长于 30 字才用（过短的多为消歧义/占位文本）
_MIN_EXTRACT_CHARS = 30


# --- 目标行选取 -------------------------------------------------------------


def _query_targets(session, *, limit: int) -> list[Poi]:
    return (
        session.query(Poi)
        .filter(Poi.status == "active")
        .filter(or_(Poi.intro.is_(None), Poi.intro == ""))
        .limit(limit)
        .all()
    )


def _city_match(row_city: str | None, want_city: str) -> bool:
    # 去掉「市」后缀再比对（refresh_pois 同款口径）
    return (row_city or "").removesuffix("市") == want_city.removesuffix("市")


def select_targets(
    session_factory, *, limit: int = 100, city: str | None = None
) -> list[Poi]:
    """intro 为空且 active 的行，LIMIT --limit，--city 去「市」比对过滤。"""
    with session_factory() as session:
        rows = _query_targets(session, limit=limit)
    if city is not None:
        rows = [r for r in rows if _city_match(r.city, city)]
    return rows


# --- Wikidata / Wikipedia 客户端（httpx.Client 可注入） ----------------------


def _search_entity(http: httpx.Client, name_zh: str) -> str | None:
    resp = http.get(
        _WIKIDATA_API,
        params={
            "action": "wbsearchentities",
            "language": "zh",
            "uselang": "zh",
            "format": "json",
            "limit": "1",
            "search": name_zh,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    search = data.get("search") if isinstance(data, dict) else None
    if isinstance(search, list) and search and isinstance(search[0], dict):
        entity_id = search[0].get("id")
        if isinstance(entity_id, str) and entity_id:
            return entity_id
    return None


def _fetch_entity(http: httpx.Client, qid: str) -> tuple[dict, str | None]:
    """返回 (claims, zhwiki sitelink title)。"""
    resp = http.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    resp.raise_for_status()
    data = resp.json()
    entities = data.get("entities") if isinstance(data, dict) else None
    entity = entities.get(qid) if isinstance(entities, dict) else None
    if not isinstance(entity, dict):
        return {}, None
    claims = entity.get("claims")
    claims = claims if isinstance(claims, dict) else {}
    sitelinks = entity.get("sitelinks")
    sitelinks = sitelinks if isinstance(sitelinks, dict) else {}
    zhwiki = sitelinks.get("zhwiki")
    zhwiki = zhwiki if isinstance(zhwiki, dict) else {}
    title = zhwiki.get("title")
    return claims, (title if isinstance(title, str) and title else None)


def _p18_filename(claims: dict) -> str | None:
    p18 = claims.get("P18")
    if isinstance(p18, list) and p18 and isinstance(p18[0], dict):
        mainsnak = p18[0].get("mainsnak")
        if isinstance(mainsnak, dict):
            datavalue = mainsnak.get("datavalue")
            if isinstance(datavalue, dict):
                value = datavalue.get("value")
                if isinstance(value, str) and value:
                    return value
    return None


def _photos_from_p18(filename: str) -> list[dict]:
    # Commons Special:FilePath 会 302 到原图缩放版；只存外链不下载。
    # license 简化写 CC——外链页自带署名与授权信息。
    return [
        {
            "url": (
                "https://commons.wikimedia.org/wiki/Special:FilePath/"
                f"{quote(filename)}?width=800"
            ),
            "source": "wikimedia",
            "license": "CC",
        }
    ]


def _wiki_extract(http: httpx.Client, title: str) -> str | None:
    resp = http.get(f"https://zh.wikipedia.org/api/rest_v1/page/summary/{quote(title)}")
    resp.raise_for_status()
    data = resp.json()
    extract = data.get("extract") if isinstance(data, dict) else None
    if isinstance(extract, str) and len(extract.strip()) > _MIN_EXTRACT_CHARS:
        return extract.strip()
    return None


# --- 主流程 -----------------------------------------------------------------


def _backfill_row(
    http: httpx.Client, row: Poi, stats: dict, *, sleep_seconds: float
) -> None:
    name = (row.name_zh or "").strip()
    needs_intro = not (row.intro or "").strip()
    needs_photos = not row.photos
    if not name:
        stats["no_entity"] += 1
        return
    time.sleep(sleep_seconds)
    qid = _search_entity(http, name)
    if not qid:
        stats["no_entity"] += 1
        return
    time.sleep(sleep_seconds)
    claims, zh_title = _fetch_entity(http, qid)
    if needs_photos:
        filename = _p18_filename(claims)
        if filename:
            row.photos = _photos_from_p18(filename)
            row.photos_source = "wikimedia"
            stats["photos_filled"] += 1
        else:
            stats["no_p18"] += 1
    if needs_intro:
        # intro_source 统一标 "wikidata" 方便统计；值实为 zh.wikipedia
        # summary 的 extract（该页面本身由 Wikidata 链出，口径归一）。
        time.sleep(sleep_seconds)
        extract = _wiki_extract(http, zh_title or name)
        if extract:
            row.intro = extract
            row.intro_source = "wikidata"
            stats["intro_filled"] += 1
        else:
            stats["no_extract"] += 1


def backfill_intro(
    session_factory,
    client: httpx.Client | None = None,
    *,
    limit: int = 100,
    city: str | None = None,
    sleep_seconds: float = _REQUEST_GAP_SECONDS,
) -> dict:
    """回填 intro/photos；只填空字段，逐行 commit。"""
    stats = {
        "targets": 0,
        "intro_filled": 0,
        "photos_filled": 0,
        "no_entity": 0,
        "no_extract": 0,
        "no_p18": 0,
        "errors": 0,
    }
    own_client = client is None
    http = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10.0)
    try:
        with session_factory() as session:
            rows = _query_targets(session, limit=limit)
            if city is not None:
                rows = [r for r in rows if _city_match(r.city, city)]
            stats["targets"] = len(rows)
            for row in rows:
                try:
                    _backfill_row(http, row, stats, sleep_seconds=sleep_seconds)
                except Exception:
                    stats["errors"] += 1
                session.commit()
    finally:
        if own_client:
            http.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="回填 POI 简介+图片（Wikidata+中文维基百科，只填空字段）"
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--city", help="只刷指定城市（如 重庆）")
    parser.add_argument(
        "--with-amap-photos",
        action="store_true",
        help="（预留）高德 photos 兜底——AmapClient 暂无返回 photos 的方法，"
        "此开关当前为 no-op，见模块 docstring",
    )
    args = parser.parse_args(argv)

    try:
        factory = get_session_factory()
    except Exception:
        factory = None
    if factory is None or not _ping(factory):
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
    stats = backfill_intro(factory, limit=args.limit, city=args.city)
    print(json.dumps(stats, ensure_ascii=True))
    return 0


def _ping(factory) -> bool:
    try:
        with factory() as session:
            session.query(Poi.id).first()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
