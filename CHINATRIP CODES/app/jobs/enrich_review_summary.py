"""POI 富化·点评综述蒸馏（review_tags → review_summary，纯库内数据）。

设计（0009 流 item 12 落地）：review_summary 是对 review_tags 的
"蒸馏"而非生成——输入是携程详情页抓下来的真实点评标签，模型只做
压缩改写，不允许引入标签之外的事实，编造面天然最小。

目标行：active 且 review_tags 非空数组、review_summary 为空。
校验门槛：15-100 字 / CJK 占比>0.3 / 无 URL 无 AI 客套 / 不复读主名。
来源标记 review_summary_source='llm_distill'；逐行只填空，失败计数不中断。

用法：
    python -m app.jobs.enrich_review_summary [--limit 500] [--concurrency 4] [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from typing import NamedTuple

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter

_DEFAULT_LIMIT = 500
_MAX_TOKENS = 1024

_SYSTEM_PROMPT = (
    "你是旅游数据编辑。把给定的点评标签提炼成一句中文综述，要求："
    "只用标签里给出的信息，绝不添加标签之外的事实；40-60 字、单段、"
    "无换行无列表无引号；除综述正文外不要输出任何其他文字。"
)


def _validate_summary(text: str, name_zh: str) -> str | None:
    """合格返回 None，否则拒绝原因码。"""
    t = (text or "").strip()
    if not (15 <= len(t) <= 100):
        return "bad_length"
    cjk = sum(1 for ch in t if "一" <= ch <= "鿿")
    if cjk / len(t) < 0.3:
        return "no_cjk"
    low = t.lower()
    if "http" in low or "```" in t or t.startswith(("以下是", "这是")):
        return "meta_text"
    if any(h in low for h in ("作为ai", "抱歉", "无法确定")):
        return "hedge"
    if name_zh and t == name_zh.strip():
        return "echo"
    return None


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(
                Poi.status == "active",
                Poi.review_tags.isnot(None),
                Poi.review_summary.is_(None),
            )
            .order_by(Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str
    tags: list[str]


def _write(session_factory, poi_id, summary: str) -> bool:
    with session_factory() as session:
        row = session.get(Poi, poi_id)
        if row is None or row.review_summary is not None:
            return False
        row.review_summary = summary
        row.review_summary_source = "llm_distill"
        session.commit()
        return True


async def _process_row(
    adapter, factory, t: _Target, sem: asyncio.Semaphore, stats: dict
) -> None:
    user = f"景点：{t.name}（{t.city or '未知'}）\n点评标签：{'、'.join(t.tags)}"
    async with sem:
        try:
            result = await adapter.chat(
                [
                    ChatMessage(role="system", content=_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user),
                ],
                temperature=0.3,
                max_tokens=_MAX_TOKENS,
            )
        except Exception:
            stats["errors"] += 1
            return
    stats["tokens_in"] += result.tokens_in
    stats["tokens_out"] += result.tokens_out
    reason = _validate_summary(result.content, t.name)
    if reason is not None:
        stats["rejected"] += 1
        stats["rejected_by_reason"][reason] = (
            stats["rejected_by_reason"].get(reason, 0) + 1
        )
        return
    if await asyncio.to_thread(_write, factory, t.poi_id, result.content.strip()):
        stats["filled"] += 1
        if len(stats["samples"]) < 8:
            stats["samples"].append(
                {"name": t.name, "tags": t.tags, "summary": result.content.strip()}
            )


async def enrich(factory, adapter, *, limit: int, concurrency: int) -> dict:
    stats = {
        "targets": 0,
        "filled": 0,
        "rejected": 0,
        "rejected_by_reason": {},
        "errors": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "samples": [],
    }
    rows = select_targets(factory, limit=limit)
    stats["targets"] = len(rows)
    targets = [
        _Target(
            r.id,
            (r.name_zh or "").strip(),
            (r.city or "").strip(),
            list(r.review_tags) if isinstance(r.review_tags, list) and r.review_tags else [],
        )
        for r in rows
        if (r.name_zh or "").strip() and r.review_tags
    ]
    sem = asyncio.Semaphore(max(1, concurrency))
    await asyncio.gather(
        *(_process_row(adapter, factory, t, sem, stats) for t in targets)
    )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int) -> None:
    rows = select_targets(session_factory, limit=limit)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))
    for r in rows[:3]:
        print(
            json.dumps(
                {"city": r.city, "name": r.name_zh, "tags": list(r.review_tags or [])},
                ensure_ascii=True,
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Distill review_tags into review_summary"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    settings = get_settings()
    if not settings.glm_api_key:
        print(json.dumps({"error": "glm_api_key is empty"}, ensure_ascii=True))
        return 1
    adapter = ZhipuGLMAdapter(
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
        model=settings.glm_model_flash,
        timeout_seconds=settings.glm_timeout_seconds,
    )
    stats = asyncio.run(
        enrich(factory, adapter, limit=args.limit, concurrency=args.concurrency)
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
