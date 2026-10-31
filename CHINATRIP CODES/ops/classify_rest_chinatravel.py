"""chinatravel 餐厅表错标行分类修复（一次性 ops 作业，幂等可续跑）。

背景（2026-10-31）：restaurants 表 source='chinatravel' 的 12,171 行 cuisine
全空，抽样显示 CSV 的 type 列把大量酒店/景点/展馆/交通枢纽错标为 restaurant
（如 亚朵酒店、亭林园、生命的纪元、北京西站），但也混有真餐厅（鱼鲜生、
大無烧肉…）。真餐厅缺 cuisine →「无中文源可译」。

本作业逐行用 GLM 分类（名称+review_tags）：
  * restaurant → 回填 cuisine（中文 2-8 字标签；cuisine_en 由既有翻译管线接续）
  * hotel/attraction/transport/other → restaurants.status='inactive'（软隐藏，
    可逆；对应景点 pois 表已有或由 attraction 导入器负责）
只填空原则：cuisine 仅在为空时写；status 仅在 active/NULL 时降级。

用法：python ops/classify_rest_chinatravel.py [--concurrency 6] [--limit 0]
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
from app.models import Restaurant
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter

_SYSTEM = (
    "你是旅游数据清洗员。判断条目是否为可就餐的餐厅/餐饮门店（含茶馆咖啡烘焙"
    "等餐饮业态）。hotel=酒店宾馆民宿，attraction=景点公园博物馆展览乐园剧场街区，"
    "transport=车站机场码头。若是餐厅，再给菜系或业态标签（中文2-8字，如 川菜/"
    "粤菜/火锅/日料/西餐/咖啡烘焙/自助餐）。只输出一行JSON，格式："
    '{"kind":"restaurant|hotel|attraction|transport|other","cuisine":"川菜"}'
    "（非餐厅时 cuisine 为空字符串），不要输出任何其他文字。"
)

_KINDS = {"restaurant", "hotel", "attraction", "transport", "other"}


def _parse(text: str) -> tuple[str, str] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    kind = str(obj.get("kind", "")).strip().lower()
    cuisine = str(obj.get("cuisine", "")).strip()
    if kind not in _KINDS:
        return None
    if kind == "restaurant":
        if not cuisine or len(cuisine) > 12:
            return None
        if not any("一" <= ch <= "鿿" for ch in cuisine):
            return None
        return kind, cuisine
    return kind, ""


async def amain(adapter, factory, sem_size: int) -> dict:
    stats = {
        "targets": 0,
        "restaurant_cuisine_filled": 0,
        "deactivated": {"hotel": 0, "attraction": 0, "transport": 0, "other": 0},
        "unparsed": 0,
        "errors": 0,
    }
    sem = asyncio.Semaphore(sem_size)

    async def one(row_id, name, tags):
        nonlocal_placeholder = None
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
            kind, cuisine = parsed
            with factory() as session:
                row = session.get(Restaurant, row_id)
                if row is None:
                    return
                changed = False
                if kind == "restaurant":
                    if not row.cuisine and cuisine:
                        row.cuisine = cuisine
                        changed = True
                        stats["restaurant_cuisine_filled"] += 1
                else:
                    if row.status is None or row.status == "active":
                        row.status = "inactive"
                        changed = True
                        stats["deactivated"][kind] = (
                            stats["deactivated"].get(kind, 0) + 1
                        )
                if changed:
                    session.commit()

    with factory() as session:
        rows = (
            session.query(Restaurant.id, Restaurant.name_zh, Restaurant.review_tags)
            .filter(
                Restaurant.source == "chinatravel",
                Restaurant.cuisine.is_(None),
                or_(Restaurant.status.is_(None), Restaurant.status == "active"),
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
            )
            for rid, name, tags in rows
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
