"""pois 表 chinatravel 行 category 兜底（一次性）：对 category IS NULL 的
chinatravel 行做 GLM 分类回填——酒店→hotel（2026-10-31 用户拍板），其余按
subtype 经 normalize_category 归一，归不上保持 NULL。幂等可续跑。

用法：python ops/backfill_poi_categories.py [--concurrency 6]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter
from app.services.poi_seed import normalize_category

_SYSTEM = (
    "你是旅游数据分类员。给条目一个中文类别词（2-6字）：博物馆/纪念馆、公园/"
    "广场、历史遗迹、寺庙/教堂、自然风光、游乐园、动物园/植物园、观景台/地标、"
    "文化村/古镇、酒店/宾馆/民宿、车站/机场/码头、展览/演出、街区/商圈、其他。"
    '只输出JSON：{"subtype":"博物馆"}，不要输出任何其他文字。'
)


def _parse(text: str) -> str | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        sub = str(json.loads(m.group(0)).get("subtype", "")).strip()
    except ValueError:
        return None
    return sub[:12] or None


async def amain(adapter, factory, sem_size: int) -> dict:
    stats = {
        "targets": 0,
        "hotel": 0,
        "normalized": 0,
        "unmapped": 0,
        "unparsed": 0,
        "errors": 0,
    }
    sem = asyncio.Semaphore(sem_size)

    async def one(pid, name):
        async with sem:
            try:
                result = await adapter.chat(
                    [
                        ChatMessage(role="system", content=_SYSTEM),
                        ChatMessage(role="user", content=f"名称：{name}"),
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                )
            except Exception:
                stats["errors"] += 1
                return
            sub = _parse(result.content)
            if sub is None:
                stats["unparsed"] += 1
                return
            cat = (
                "hotel"
                if "酒店" in sub or "宾馆" in sub or "民宿" in sub
                else normalize_category(sub)
            )
            with factory() as session:
                row = session.get(Poi, pid)
                if row is None or row.category is not None:
                    return
                if cat is None:
                    stats["unmapped"] += 1
                    return
                row.category = cat
                session.commit()
                stats["hotel" if cat == "hotel" else "normalized"] += 1

    with factory() as session:
        rows = (
            session.query(Poi.id, Poi.name_zh)
            .filter(
                Poi.source == "chinatravel",
                Poi.category.is_(None),
                or_(Poi.status.is_(None), Poi.status == "active"),
            )
            .all()
        )
    stats["targets"] = len(rows)
    await asyncio.gather(*(one(pid, name or "") for pid, name in rows))
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
    out = asyncio.run(amain(adapter, get_session_factory(), args.concurrency))
    print(json.dumps(out, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
