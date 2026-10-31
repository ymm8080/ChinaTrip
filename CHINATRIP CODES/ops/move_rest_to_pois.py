"""chinatravel 餐厅表错标行修复 v2：分类 → 归位（搬移，不再 inactive）。

背景：restaurants 表 source='chinatravel' 的 12k+ 行 cuisine 全空，CSV type
列错标（酒店/景点/交通枢纽混入），且源 parquet 已清理、type 不可回溯 → 用
GLM 分类（名称+review_tags 信号）后处置：
  * restaurant → 回填 cuisine（中文标签）；若 status 被早前误置 inactive 则
    恢复 active（修复 v1 副作用）；
  * hotel/attraction/transport/other → 经 seed_upsert 搬入 pois 表
    （category=中文子类，经 normalize_category 归一，能归多少归多少），
    成功（created/exists）后删除 restaurants 行；搬移失败保留原行不动。

幂等可续跑：目标集 = source='chinatravel' AND cuisine IS NULL（任意 status），
随处理逐批缩小的终点。用法：
    python ops/move_rest_to_pois.py [--concurrency 6]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geoalchemy2.shape import to_shape

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi, Restaurant
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter
from app.services.poi_seed import seed_upsert

_SYSTEM = (
    "你是旅游数据清洗员。判断条目是否为可就餐的餐厅/餐饮门店（含茶馆咖啡烘焙"
    "等餐饮业态）。hotel=酒店宾馆民宿，attraction=景点公园博物馆展览乐园剧场街区，"
    "transport=车站机场码头。若是餐厅，cuisine 给菜系或业态标签（中文2-8字，如 "
    "川菜/粤菜/火锅/日料/西餐/咖啡烘焙/自助餐）；若不是餐厅，subtype 给中文类别词"
    "（如 博物馆/公园/广场/酒店/古镇/老街/车站/机场/剧场/展览/乐园/其他）。"
    "只输出一行JSON："
    '{"kind":"restaurant|hotel|attraction|transport|other","cuisine":"川菜",'
    '"subtype":"博物馆"}（餐厅时 subtype 留空、非餐厅时 cuisine 留空），'
    "不要输出任何其他文字。"
)

_KINDS = {"restaurant", "hotel", "attraction", "transport", "other"}


def _parse(text: str) -> tuple[str, str, str] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    kind = str(obj.get("kind", "")).strip().lower()
    cuisine = str(obj.get("cuisine", "")).strip()
    subtype = str(obj.get("subtype", "")).strip()
    if kind not in _KINDS:
        return None
    if kind == "restaurant":
        if not cuisine or len(cuisine) > 12:
            return None
        if not any("一" <= ch <= "鿿" for ch in cuisine):
            return None
        return kind, cuisine, ""
    return kind, "", subtype[:12]


def _lonlat(geom) -> tuple[float, float] | None:
    if geom is None:
        return None
    try:
        p = to_shape(geom)
        return (p.x, p.y)
    except Exception:
        return None


async def amain(adapter, factory, sem_size: int) -> dict:
    stats = {
        "targets": 0,
        "restaurant_cuisine_filled": 0,
        "restaurant_reactivated": 0,
        "moved_to_pois_created": 0,
        "moved_to_pois_exists": 0,
        "deleted_rest_rows": 0,
        "move_failed_kept": 0,
        "unparsed": 0,
        "errors": 0,
    }
    sem = asyncio.Semaphore(sem_size)

    async def one(rid, name, tags, city):
        async with sem:
            user = f"名称：{name}\n标签：{tags}"
            try:
                result = await adapter.chat(
                    [
                        ChatMessage(role="system", content=_SYSTEM),
                        ChatMessage(role="user", content=user),
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                )
            except Exception:
                stats["errors"] += 1
                return
            parsed = _parse(result.content)
            if parsed is None:
                stats["unparsed"] += 1
                return
            kind, cuisine, subtype = parsed
            try:
                with factory() as session:
                    row = session.get(Restaurant, rid)
                    if row is None:
                        return
                    if kind == "restaurant":
                        if not row.cuisine and cuisine:
                            row.cuisine = cuisine
                            stats["restaurant_cuisine_filled"] += 1
                        if row.status == "inactive":
                            row.status = "active"
                            stats["restaurant_reactivated"] += 1
                        session.commit()
                        return
                    # 非餐饮：搬入 pois 后删除 restaurants 行
                    lonlat = _lonlat(row.location)
                    wgs = _lonlat(row.wgs84_location)
                    # kind=hotel 强制 hotel（2026-10-31）：GLM subtype 自由
                    # 文本可能给「自然风光」等景点词，按 subtype 归一会把
                    # 住宿行错归 nature/attraction 污染景点池
                    cat = "hotel" if kind == "hotel" else (subtype or None)
                    res = seed_upsert(
                        factory,
                        Poi,
                        source="chinatravel",
                        source_poi_id=row.source_poi_id,
                        city=row.city or city,
                        name_zh=row.name_zh or name,
                        category=cat,
                        lonlat=lonlat,
                        wgs84_lonlat=wgs,
                        origin="chinatravel",
                        tags=row.review_tags
                        if isinstance(row.review_tags, list) and row.review_tags
                        else None,
                    )
                    if res in ("created", "exists"):
                        stats[f"moved_to_pois_{res}"] += 1
                        session.delete(row)
                        session.commit()
                        stats["deleted_rest_rows"] += 1
                    else:
                        stats["move_failed_kept"] += 1
            except Exception:
                stats["errors"] += 1

    with factory() as session:
        rows = (
            session.query(
                Restaurant.id,
                Restaurant.name_zh,
                Restaurant.review_tags,
                Restaurant.city,
            )
            .filter(
                Restaurant.source == "chinatravel",
                Restaurant.cuisine.is_(None),
            )
            .all()
        )
    stats["targets"] = len(rows)
    await asyncio.gather(
        *(
            one(
                rid,
                name or "",
                json.dumps(tags, ensure_ascii=False)[:120]
                if isinstance(tags, list)
                else str(tags or "")[:120],
                city,
            )
            for rid, name, tags, city in rows
        )
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.glm_api_key:
        print('{"error": "glm_api_key is empty"}')
        return 1
    adapter = ZhipuGLMAdapter(
        base_url=settings.glm_base_url,
        api_key=settings.glm_api_key,
        model=settings.glm_model,
        timeout_seconds=60,
    )
    factory = get_session_factory()
    out = asyncio.run(amain(adapter, factory, args.concurrency))
    print(json.dumps(out, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
