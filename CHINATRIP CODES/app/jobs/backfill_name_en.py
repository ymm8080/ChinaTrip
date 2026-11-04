"""POI 英文名 LLM 批量回填（智谱 GLM，骨架行 name_en 只填空）。

背景（2026-11-03）：评级名单骨架行（street 200 / histown 302 本会话
入库）无 name_en——POIS_DATASOURCE 骨架规约要求名单类行 name_en
100%。本 job 复用 ZhipuGLMAdapter 批量译名，专有名词按「拼音专名 +
通名英译」惯例（周庄镇 → Zhouzhuang Town）。

实测硬规格沿用 backfill_intro_llm 探针：glm-5.3-flash 思考模型一律
max_tokens=1024（150 会被思考吃光返回空串）；Semaphore 有界并发，
每条完成即独立短 session 写库。

铁律：只填空——写库前复查 name_en 仍为空才 UPDATE；产出必过
_validate_en（非空 / 纯拉丁为主 / 无 CJK / 长度 ≤120 / 不等于原名）
校验，不合格计 rejected 并带原因不入库。LLMError/其它异常计 errors
继续下一条，不中断。

用法：
    python -m app.jobs.backfill_name_en [--sources street,histown]
        [--limit 2000] [--concurrency 6] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter

_MAX_TOKENS = 1024  # 思考模型：额度不足会被思考吃光（探针见 intro_llm docstring）
_MAX_CONCURRENCY = 8
_MAX_EN_LEN = 160  # 全地址链名（34+ 汉字）忠实译文可过 120，160 兜住全部实测
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")

_SYSTEM = (
    "你是旅游 POI 双语译者。把中文景点/街区/古镇/古村/考古遗址公园名译成"
    "标准英文译名：专名用拼音或通行英译，通名意译（镇→Town、村→Village、"
    "古城→Ancient Town、街区→Block/Historic Area、遗址公园→Archaeological"
    ' Site Park、 Kangba→音译）。只输出一行 JSON：{"en":"Zhouzhuang Town"}；'
    '确实无法译出（纯无意义代号）才输出 {"en":null}。不要输出任何其他文字。'
)


def _user_msg(city: str, name: str, label: str | None) -> str:
    extra = f"\n体系：{label}" if label else ""
    return f"城市：{city}\n中文名：{name}{extra}"


def _validate_en(en: str | None, source_name: str) -> tuple[bool, str]:
    if not en or not en.strip():
        return False, "empty"
    en = en.strip().strip("\"'`")
    if not en:
        return False, "empty"
    if len(en) > _MAX_EN_LEN:
        return False, f"too_long:{len(en)}"
    if _CJK.search(en):
        return False, "has_cjk"
    if not _LATIN.search(en):
        return False, "no_latin"
    if en.strip().lower() == (source_name or "").strip().lower():
        return False, "same_as_source"
    return True, en


def _parse_en(content: str) -> str | None:
    import json as _json

    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        obj = _json.loads(m.group(0))
    except ValueError:
        return None
    en = obj.get("en")
    return en if isinstance(en, str) else None


def select_targets(session_factory, *, sources: list[str], limit: int) -> list[Poi]:
    with session_factory() as session:
        rows = (
            session.query(Poi)
            .filter(
                Poi.source.in_(sources),
                Poi.status == "active",
            )
            .all()
        )
    missing = [
        r for r in rows if not (r.name_en or "").strip() and (r.name_zh or "").strip()
    ]
    return missing[:limit] if limit > 0 else missing


async def _process_row(
    adapter,
    session_factory,
    row: Poi,
    sem: asyncio.Semaphore,
    stats: dict,
) -> None:
    async with sem:
        try:
            result = await adapter.chat(
                [
                    ChatMessage(role="system", content=_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=_user_msg(
                            row.city or "",
                            row.name_zh,
                            (row.tags or [None])[0] if row.tags else None,
                        ),
                    ),
                ],
                temperature=0.2,
                max_tokens=_MAX_TOKENS,
            )
        except Exception:
            stats["errors"] += 1
            return
        en = _parse_en(result.content)
        ok, val = _validate_en(en, row.name_zh)
        if not ok:
            stats["rejected"] += 1
            stats.setdefault("reject_detail", []).append(
                {"name": row.name_zh, "why": val}
            )
            return
        with session_factory() as session:
            fresh = session.get(Poi, row.id)
            if fresh is None:
                stats["gone"] += 1
                return
            if (fresh.name_en or "").strip():
                stats["already_filled"] += 1
                return
            fresh.name_en = val
            session.commit()
        stats["filled"] += 1


async def backfill_name_en(
    session_factory,
    adapter,
    *,
    sources: list[str],
    limit: int = 0,
    concurrency: int = 6,
) -> dict:
    """有界并发回填；每条完成即写库，只填空语义不破。"""
    targets = select_targets(session_factory, sources=sources, limit=limit)
    stats: dict = {
        "targets": len(targets),
        "filled": 0,
        "already_filled": 0,
        "rejected": 0,
        "errors": 0,
        "gone": 0,
    }
    sem = asyncio.Semaphore(max(1, min(concurrency, _MAX_CONCURRENCY)))
    await asyncio.gather(
        *(_process_row(adapter, session_factory, t, sem, stats) for t in targets)
    )
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="POI 英文名 LLM 批量回填")
    parser.add_argument(
        "--sources",
        default="street,histown",
        help="逗号分隔的 source 列表（默认 street,histown）",
    )
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数（0=全量）")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true", help="只盘点目标数，不调 LLM")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.glm_api_key:
        print(json.dumps({"error": "glm_api_key is empty"}, ensure_ascii=True))
        return 1
    adapter = ZhipuGLMAdapter(
        base_url=settings.glm_base_url,
        api_key=settings.glm_api_key,
        model=settings.glm_model,
        timeout_seconds=60,
    )
    factory = get_session_factory()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if args.dry_run:
        targets = select_targets(factory, sources=sources, limit=args.limit)
        sample = [{"city": t.city, "name_zh": t.name_zh} for t in targets[:8]]
        print(
            json.dumps(
                {"dry_run": True, "targets": len(targets), "sample": sample},
                ensure_ascii=True,
            )
        )
        return 0
    stats = asyncio.run(
        backfill_name_en(
            factory,
            adapter,
            sources=sources,
            limit=args.limit,
            concurrency=args.concurrency,
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
