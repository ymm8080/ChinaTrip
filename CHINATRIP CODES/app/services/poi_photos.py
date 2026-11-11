"""POI 照片回源链（DESIGN poi_photos_functional_design 2026-11-11 §3-F2）.

点击触发确定性回源：库空 → 按链序现拉，首个非空命中即停；链序唯一
定义点在本文件（点击端点与 backfill_photos job 共用）：

    amap v5 place/detail（row.source=='amap' 且有 source_poi_id）
      → amap v3 place/text 按名搜（extensions=all 经 _normalize_poi 回
        photos；覆盖无 amap id 行与 v5 空图兜底）
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
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.services.amap_client import AmapQuotaExhaustedError

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


async def _wikimedia(name_zh: str) -> list[dict] | None:
    return await asyncio.to_thread(_wikimedia_p18_sync, name_zh)


async def fetch_photo_chain(
    row: Any, *, amap: Any | None
) -> tuple[list[dict] | None, str | None]:
    """按链序现拉 photos，首个非空命中即停。

    row：Poi ORM 行（或同形状 SimpleNamespace，测试用）。单源异常记
    warning 后跳下一源，不拖垮整链；全空返回 (None, None)——调用方
    只落 fetched_at 戳、不写 photos（只填空铁律）。
    """
    name_zh = (getattr(row, "name_zh", None) or "").strip()
    city = getattr(row, "city", None)
    if amap is not None:
        amap_id = getattr(row, "source_poi_id", None)
        if getattr(row, "source", None) == "amap" and amap_id:
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
