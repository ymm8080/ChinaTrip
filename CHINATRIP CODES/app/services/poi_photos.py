"""POI 照片回源链（DESIGN poi_photos_functional_design 2026-11-11 §3-F2）.

点击触发确定性回源：库空 → 按链序现拉，首个非空命中即停；链序唯一
定义点在本文件（点击端点与 backfill_photos job 共用）：

    amap v5 place/detail（row.source=='amap' 且有 source_poi_id）
      → amap v5 place/around 按坐标邻近搜（2026-11-12 restaurants 回源：
        无 amap id 但有坐标的行走本档；v3 place/text 被 WAF 整族拦下，
        around 独立配额池/独立风控不受影响——本文件 httpx 直调，见
        _amap_around_photos 注记）
      → amap v3 place/text 按名搜（extensions=all 经 _normalize_poi 回
        photos；仅剩无坐标的兜底场景）
      → wikimedia P18（复用 backfill_intro 的 Wikidata 链；同步 httpx，
        asyncio.to_thread 包裹进 async 链）

百度/腾讯暂不入链：两家 place_hours 的代码路径（baidu_client
._hours_result / tencent_client.place_hours）只解析 hours/rating，不透
photos——厂商响应里是否真含图待实测探针，含图再补解析接链（设计 §2
注记）。F3 AI 搜索兜底（llm_web）能力闸 _PHOTO_AI_ENABLED=False 维持
关闭，不在本链。

数据契约（§4）：photos=[{title,url}] ≤8 条、url 必须 http(s) 绝对地址；
只填空语义在调用方（端点/job 写库时判空）。冷却：24h 键
photos_fetched_at，"尝试即落戳"（拉空也落），防连点烧图商配额。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.services.amap_client import (
    _BROWSER_HEADERS,
    AmapError,
    AmapQuotaExhaustedError,
    _is_punish_page,
    _is_quota_exhausted,
    _name_like,
)

logger = logging.getLogger(__name__)

#: 点击冷却窗口（拍板值 §3-F2）；backfill/job 路径不走冷却。
COOLDOWN = timedelta(hours=24)

#: photos_source 枚举（§4）。wikimedia P18 之外的 wiki_media/official 等
#: 由后续兜底源接入时使用，先注册防脏值。
PHOTO_SOURCES = (
    "wikimedia",
    "amap",
    "ctrip",
    "baidu",
    "tencent",
    "wiki_media",
    "official",
    "baike",
    "bing_image",
    "llm_web",
)

_MAX_PHOTOS = 8

_AMAP_TIMEOUT_SECONDS = 10.0

#: v5 /place/around 照片档参数（同 amap_client._search_hours_around 口径）：
#: radius 3km 邻近、page_size 10 一次取回多候选本地匹配。
_AMAP_AROUND_RADIUS_M = "3000"
_AMAP_AROUND_PAGE_SIZE = 10

#: 名称去括号变体（"老火锅（解放碑店）"→"老火锅"）。
_BRACKET_RE = re.compile(r"[（(【\[].*?[）)】\]]")


def normalize_photos(raw: object) -> list[dict]:
    """[{title,url}] 收口：url 必须 http(s) 绝对地址，按 url 去重，≤8 条。

    title 缺省空串（灯箱底部来源小字已带名称，title 仅图注直出）。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str):
            continue
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        title = item.get("title")
        out.append(
            {"title": title.strip() if isinstance(title, str) else "", "url": url}
        )
        if len(out) >= _MAX_PHOTOS:
            break
    return out


async def _amap_by_id(client: Any, amap_id: str) -> list[dict] | None:
    r = await client.place_hours(amap_id)
    return normalize_photos((r or {}).get("photos")) or None


async def _amap_by_name(client: Any, name: str, city: str | None) -> list[dict] | None:
    if not name:
        return None
    hits = await client.search_poi(name, city=city or None)
    for hit in hits or []:
        photos = normalize_photos((hit or {}).get("photos"))
        if photos:
            return photos
    return None


def _row_lonlat(location: object) -> tuple[float, float] | None:
    """行坐标 → (lon, lat)，取不出有效数即 None。

    兼容三种形状（fetch_photo_chain 对行对象零假设，SimpleNamespace 测试
    行也要能走）：Geography/WKB 列（ORM 行，geoalchemy2 to_shape →
    shapely .x/.y）、"lon,lat" 逗号串（refresh_pois 同款）、(lon, lat)
    序列或带 .lon/.lat 属性的 GeoPoint（内存候选行/测试行）。
    """
    if location is None:
        return None
    if isinstance(location, str):
        # WKT（job 侧 func.ST_AsText 出参，"POINT(lon lat)"）优先剥壳，
        # 其余按 "lon,lat" 逗号串（refresh_pois 同款）
        wkt = location.strip()
        if wkt.upper().startswith("POINT(") and wkt.endswith(")"):
            wkt = wkt[len("POINT(") : -1]
        parts = wkt.replace(",", " ").split()
        if len(parts) != 2:
            return None
        try:
            return (float(parts[0]), float(parts[1]))
        except ValueError:
            return None
    if isinstance(location, (list, tuple)) and len(location) == 2:
        try:
            return (float(location[0]), float(location[1]))
        except (TypeError, ValueError):
            return None
    lon = getattr(location, "lon", None)
    lat = getattr(location, "lat", None)
    if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
        return (float(lon), float(lat))
    try:  # Geography 列（WKBElement）：现成提取器只有 geoalchemy2 to_shape
        from geoalchemy2.shape import to_shape

        point = to_shape(location)
        return (float(point.x), float(point.y))
    except Exception:
        return None


def _match_terms(name_zh: str) -> list[str]:
    """around 本地名匹配词：全名 + 去括号变体，保序去重。

    匹配口径 amap_client._name_like（双向包含、去空格、单字不参与），
    在 _amap_around_photos 内逐候选套用。
    """
    base = name_zh.strip()
    out: list[str] = []
    for term in (base, _BRACKET_RE.sub("", base).strip()):
        if term and term not in out:
            out.append(term)
    return out


async def _amap_around_photos(
    name_zh: str, lonlat: tuple[float, float]
) -> list[dict] | None:
    """v5 /place/around 按坐标邻近搜照片（无 amap id 行的照片档）。

    2026-11-12 注记：amap_client.py 当前有并行会话未提交改动，不宜
    在其上扩公开方法——本函数 httpx 直调同端点，参数与判罚口径对齐
    AmapClient._search_hours_around（keywords+location+radius 3km+
    page_size 10+show_fields=business,photos；headers/配额判定/WAF
    处罚页判定/名称匹配复用其唯一实现，不复制缩短版）。命中名（
    _name_like 双向包含）且 photos 非空才返回。配额尽（10021）原样
    上抛 AmapQuotaExhaustedError 供链上熔断；WAF 处罚/超时等其余异常
    上抛 AmapError 由 fetch_photo_chain 记 warning 降级 wikimedia。
    """
    params = {
        "key": get_settings().amap_api_key,
        "keywords": name_zh,
        "location": f"{lonlat[0]:.6f},{lonlat[1]:.6f}",
        "radius": _AMAP_AROUND_RADIUS_M,
        "page_size": str(_AMAP_AROUND_PAGE_SIZE),
        "show_fields": "business,photos",
        "output": "JSON",
    }
    async with httpx.AsyncClient(
        timeout=_AMAP_TIMEOUT_SECONDS, headers=_BROWSER_HEADERS
    ) as http:
        response = await http.get(
            "https://restapi.amap.com/v5/place/around", params=params
        )
    try:
        data = response.json()
    except ValueError as exc:
        if _is_punish_page(response.content):
            raise AmapError(
                "amap WAF deny page (bixi punish) — around photos skip"
            ) from exc
        raise AmapError("amap returned non-JSON body") from exc
    if not isinstance(data, dict):
        raise AmapError("amap returned unexpected JSON shape")
    if data.get("status") != "1":
        if _is_quota_exhausted(data):
            raise AmapQuotaExhaustedError(
                str(data.get("info") or "amap daily quota exhausted"),
                str(data.get("infocode") or ""),
            )
        raise AmapError(
            str(data.get("info") or "amap request failed"),
            str(data.get("infocode") or ""),
        )
    pois = data.get("pois")
    terms = _match_terms(name_zh)
    poi = None
    if isinstance(pois, list):
        poi = next(
            (
                p
                for p in pois
                if isinstance(p, dict)
                and any(_name_like(p.get("name", ""), t) for t in terms)
            ),
            None,
        )
    if poi is None:
        return None
    photos = normalize_photos(poi.get("photos"))
    if photos:
        logger.debug(
            "photo chain: amap around hit name=%s matched=%s",
            name_zh,
            poi.get("name"),
        )
    return photos or None


def _wikimedia_p18_sync(name_zh: str) -> list[dict] | None:
    """Wikidata P18 → Commons Special:FilePath 外链（同步 httpx）。

    复用 backfill_intro 的实体链函数与合规 UA（api.wikimedia.org/wikidata
    要求 UA，否则 403 robot policy）；只存外链不下载。
    """
    from app.jobs.backfill_intro import (  # 就地 import 防 jobs↔services 环
        API_USER_AGENT,
        USER_AGENT,
        _fetch_entity,
        _p18_filename,
        _photos_from_p18,
        _search_entity,
    )

    if not name_zh:
        return None
    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Api-User-Agent": API_USER_AGENT},
        timeout=10.0,
    ) as http:
        qid = _search_entity(http, name_zh)
        if not qid:
            return None
        claims, _ = _fetch_entity(http, qid)
        filename = _p18_filename(claims)
        if not filename:
            return None
    # _photos_from_p18 出 [{url,source,license}]，收口成 {title,url}
    return (
        normalize_photos(
            [
                {"title": "", "url": p["url"]}
                for p in _photos_from_p18(filename)
                if isinstance(p, dict) and p.get("url")
            ]
        )
        or None
    )


async def _ctrip_photos(name_zh: str, city: str) -> list[dict] | None:
    """ctrip 便车：CtripHoursReader 详情页响应顺带抠图（零新增请求）。

    读者为进程级 lazy 单例（长会话 cookie 罐过闸率远高于新会话）；
    城市不在 CITY_SLUGS 393 城内 reader 自动返 None。dimg 域白名单
    在 ctrip_hours.parse_detail_photos 内收口。
    """
    from app.services.ctrip_hours import get_ctrip_hours

    reader = get_ctrip_hours()
    fields = await reader.detail_fields_for(city, name_zh)
    if not fields:
        return None
    return normalize_photos(fields.get("photos")) or None


async def _wikimedia(name_zh: str) -> list[dict] | None:
    return await asyncio.to_thread(_wikimedia_p18_sync, name_zh)


# --- 2026-11-12 免费新源：Wikipedia media-list / Commons 搜索 / 官网 og ----


def _wiki_headers() -> dict[str, str]:
    from app.jobs.backfill_intro import API_USER_AGENT, USER_AGENT

    return {"User-Agent": USER_AGENT, "Api-User-Agent": API_USER_AGENT}


def _wikidata_sitelinks_sync(name_zh: str) -> dict[str, str]:
    """wbsearchentities + EntityData → {"zhwiki"/"enwiki": 页面标题}。

    media-list 需要按语言的页面标题（P18 链拿不到 enwiki），此处独立
    取 sitelinks——端点与 backfill_intro 同款，合规 UA 同串。
    """
    from app.jobs.backfill_intro import _search_entity

    if not name_zh:
        return {}
    with httpx.Client(headers=_wiki_headers(), timeout=10.0) as http:
        qid = _search_entity(http, name_zh)
        if not qid:
            return {}
        resp = http.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
        resp.raise_for_status()
        data = resp.json()
        entities = data.get("entities") if isinstance(data, dict) else {}
        entity = entities.get(qid) if isinstance(entities, dict) else {}
        sitelinks = entity.get("sitelinks") if isinstance(entity, dict) else {}
        if not isinstance(sitelinks, dict):
            return {}
        out: dict[str, str] = {}
        for key in ("zhwiki", "enwiki"):
            sl = sitelinks.get(key)
            title = sl.get("title") if isinstance(sl, dict) else None
            if isinstance(title, str) and title:
                out[key] = title
        return out


def _parse_media_items(data: object) -> list[dict]:
    """media-list 响应 → [{title,url}]。original 优先、thumb 兜底，
    协议相对 //upload.wikimedia.org 补 https:，mime 必须 image/*。"""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mime = it.get("mime")
        if not isinstance(mime, str) or not mime.startswith("image/"):
            continue
        src = None
        for key in ("original", "thumb"):
            node = it.get(key)
            if isinstance(node, dict):
                src = node.get("source") or node.get("url")
                if src:
                    break
        if not isinstance(src, str) or not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        title = it.get("title")
        out.append({"title": title if isinstance(title, str) else "", "url": src})
    return out


def _wikipedia_media_sync(name_zh: str) -> list[dict] | None:
    """Wikipedia media-list（zh→en sitelink 各试一档）→ 页面全部图片。

    api.wikimedia.org 直连可达（zh.wikipedia.org 被墙，backfill_intro
    已实测）；P18 只是页面可能的一张，media-list 收全页图——多图主力
    免费源。任一语言命中即停。
    """
    from urllib.parse import quote

    if not name_zh:
        return None
    links = _wikidata_sitelinks_sync(name_zh)
    with httpx.Client(headers=_wiki_headers(), timeout=10.0) as http:
        for key, lang in (("zhwiki", "zh"), ("enwiki", "en")):
            title = links.get(key)
            if not title:
                continue
            try:
                resp = http.get(
                    "https://api.wikimedia.org/core/v1/wikipedia/"
                    f"{lang}/page/{quote(title, safe='')}/media-list"
                )
                resp.raise_for_status()
                photos = normalize_photos(_parse_media_items(resp.json()))
            except Exception:
                logger.warning(
                    "photo chain: media-list failed, lang=%s title=%s",
                    lang,
                    title,
                    exc_info=True,
                )
                continue
            if photos:
                return photos
    return None


def _parse_commons_pages(data: object, name_zh: str) -> list[dict]:
    """Commons generator=search 响应 → [{title,url}]（relevance 序）。"""
    pages = data.get("query", {}).get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, dict):
        return []
    out: list[dict] = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        infos = page.get("imageinfo")
        info = infos[0] if isinstance(infos, list) and infos else None
        if not isinstance(info, dict):
            continue
        mime = info.get("mime")
        if not isinstance(mime, str) or not mime.startswith("image/"):
            continue
        url = info.get("thumburl") or info.get("url")
        title = page.get("title")
        # 防张冠李戴：文件名须含名称核心词（双向包含口径与 _name_like 一致）
        if isinstance(title, str) and not _name_like(title.rsplit(".", 1)[0], name_zh):
            continue
        if isinstance(url, str) and url:
            out.append({"title": title if isinstance(title, str) else "", "url": url})
    return out


def _commons_search_sync(name_zh: str) -> list[dict] | None:
    """Commons File 命名空间站内搜（免费，relevance 序，文件名含名才收）。"""
    if not name_zh:
        return None
    with httpx.Client(headers=_wiki_headers(), timeout=10.0) as http:
        resp = http.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": name_zh,
                "gsrnamespace": "6",
                "gsrlimit": "8",
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "iiurlwidth": "800",
                "format": "json",
            },
        )
        resp.raise_for_status()
        return normalize_photos(_parse_commons_pages(resp.json(), name_zh)) or None


def _official_og_sync(website: str) -> list[dict] | None:
    """官网 og:image（正确性最高的免费源：官方自选主图）。"""
    from app.services.video_reader import _OG_IMAGE_RE

    url = (website or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    with httpx.Client(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            )
        },
        timeout=10.0,
        follow_redirects=True,
    ) as http:
        resp = http.get(url)
        resp.raise_for_status()
        m = _OG_IMAGE_RE.search(resp.text)
        if not m:
            return None
        og = m.group(1).strip()
        if og.startswith("//"):
            og = "https:" + og
        from urllib.parse import urljoin

        og = urljoin(url, og)
        return normalize_photos([{"title": "", "url": og}]) or None


async def _wikipedia_media(name_zh: str) -> list[dict] | None:
    return await asyncio.to_thread(_wikipedia_media_sync, name_zh)


async def _commons_search(name_zh: str) -> list[dict] | None:
    return await asyncio.to_thread(_commons_search_sync, name_zh)


async def _official_og(website: str) -> list[dict] | None:
    return await asyncio.to_thread(_official_og_sync, website)


async def fetch_photo_chain(
    row: Any, *, amap: Any | None
) -> tuple[list[dict] | None, str | None]:
    """按链序现拉 photos，首个非空命中即停。

    row：Poi/Restaurant ORM 行（或同形状 SimpleNamespace，测试用）。
    单源异常记 warning 后跳下一源，不拖垮整链；全空返回 (None, None)
    ——调用方只落 fetched_at 戳、不写 photos（只填空铁律）。

    链序（2026-11-12 起）：amap id 有 → v5 place/detail；无 id 且行有
    坐标 → v5 place/around 邻近搜（keyword=name_zh+去括号变体，命中名
    且 photos 非空才收，见 _amap_around_photos）；无坐标 → v3 place/
    text 按名搜（旧兜底，text 端点 WAF 被拦时自然落空）；全落空 →
    wikimedia P18。
    """
    name_zh = (getattr(row, "name_zh", None) or "").strip()
    city = getattr(row, "city", None)
    amap_id = getattr(row, "source_poi_id", None)
    has_amap_id = getattr(row, "source", None) == "amap" and bool(amap_id)
    if amap is not None:
        if has_amap_id:
            try:
                photos = await _amap_by_id(amap, amap_id)
            except AmapQuotaExhaustedError:
                raise  # 配额熔断：调用方首撞即停整轮，不降级继续烧下游
            except Exception:
                logger.warning(
                    "photo chain: amap place/detail failed, amap_id=%s",
                    amap_id,
                    exc_info=True,
                )
                photos = None
            if photos:
                return photos, "amap"
        lonlat = None if has_amap_id else _row_lonlat(getattr(row, "location", None))
        if not has_amap_id and lonlat is not None and name_zh:
            # 无 amap id 但有坐标：v5 place/around（独立配额池/独立风控，
            # text 被 WAF 处罚不影响本档）。
            try:
                photos = await _amap_around_photos(name_zh, lonlat)
            except AmapQuotaExhaustedError:
                raise
            except Exception:
                logger.warning(
                    "photo chain: amap place/around photos failed, name=%s",
                    name_zh,
                    exc_info=True,
                )
                photos = None
            if photos:
                return photos, "amap"
        else:
            try:
                photos = await _amap_by_name(amap, name_zh, city)
            except AmapQuotaExhaustedError:
                raise
            except Exception:
                logger.warning(
                    "photo chain: amap name search failed, name=%s",
                    name_zh,
                    exc_info=True,
                )
                photos = None
            if photos:
                return photos, "amap"
    # ctrip 便车（2026-11-13）：复用 CtripHoursReader 长会话已发的详情页
    # 响应顺带抠图（零新增请求、零 key；壳页/未收录自然落空）——只对
    # 有城市行生效（CITY_SLUGS 393 城内）。
    if name_zh and city:
        try:
            photos = await _ctrip_photos(name_zh, city)
        except Exception:
            logger.warning(
                "photo chain: ctrip ride failed, name=%s city=%s",
                name_zh,
                city,
                exc_info=True,
            )
            photos = None
        if photos:
            return photos, "ctrip"
    # 免费维基档（2026-11-12 扩链）：media-list（页面全部图，多图主力）
    # → Commons 站内搜（文件名含名才收）→ 官网 og:image（官方自选主图）
    # → 旧 P18 兜底（media-list 覆盖不到的 P18-only 实体仍能收 1 图）。
    for fn, tag in (
        # 2026-11-12 media-list 摘除：api.wikimedia.org 网关无该 handler
        # （rest-no-match 404），zh.wikipedia.org 直连被墙——白打 2 请求/行
        (_commons_search, "wikimedia"),
    ):
        try:
            photos = await fn(name_zh)
        except Exception:
            logger.warning(
                "photo chain: %s failed, name=%s", tag, name_zh, exc_info=True
            )
            photos = None
        if photos:
            return photos, tag
    website = getattr(row, "website", None)
    if website:
        try:
            photos = await _official_og(website)
        except Exception:
            logger.warning(
                "photo chain: official og:image failed, site=%s",
                website,
                exc_info=True,
            )
            photos = None
        if photos:
            return photos, "official"
    try:
        photos = await _wikimedia(name_zh)
    except Exception:
        logger.warning(
            "photo chain: wikimedia P18 failed, name=%s", name_zh, exc_info=True
        )
        photos = None
    if photos:
        return photos, "wikimedia"
    return None, None


def in_cooldown(fetched_at: datetime | None, now: datetime) -> bool:
    """24h 冷却判定；"尝试即落戳"故拉空行同样被冷却覆盖。"""
    return fetched_at is not None and (now - fetched_at) < COOLDOWN
