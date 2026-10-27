"""POI 简介 LLM 兜底回填作业（智谱 GLM，Wikimedia 链榨干后的最后一路）。

背景（2026-10-24）：POI 库 2932 行无简介，Wikidata/zhwiki 链
（app.jobs.backfill_intro）已榨干；本 job 复用现成的 ZhipuGLMAdapter
（app.services.llm.zhipu）直接生成中文简介。直接读 config 的 glm_*
字段构造 adapter——.env 里 LLM_BACKEND=mock 是 agent 运行时开关，
与本 job 无关。

实测硬规格（探针 2026-10-24，不照做必翻车）：
  * glm-5.3-flash 是思考模型，max_tokens=150 时思考吃光全部额度、
    content 返回空串 → 调用一律 max_tokens=1024。
  * 模型对辨认不出的行常回 "SKIP\\n\\n(Note: ...英文)"——SKIP 判定
    用前缀（不分大小写），不能整串比较。
  * 单条 wall ~8.3s，2932 条串行要 6.8h → Semaphore 有界并发，
    默认 4、上限 8，每条完成即独立短 session 写库。

铁律：只填空——写库前复查 intro 仍为空才 UPDATE；intro_source='llm'
（intro_source 列 varchar(20)，够放）。产出必过 _validate_intro 纯
函数校验（长度 20-300 / CJK 占比 / URL围栏导语 / AI客套 / 复读名称
五关），不合格计 rejected 并带原因，不入库。LLMError/其它异常计
errors 继续下一条，不中断。

用法：
    python -m app.jobs.backfill_intro_llm [--limit 5000]
        [--concurrency 4] [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from typing import NamedTuple

from sqlalchemy import case, or_

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter

_DEFAULT_LIMIT = 5000
# 思考模型：给足额度让正文能出全（探针见模块 docstring）
_MAX_TOKENS = 1024
_MAX_CONCURRENCY = 8
# source 优先级：名气大的先补，未知源排最后
_SOURCE_PRIORITY = (
    "unesco",
    "5a",
    "museum1",
    "museum2",
    "museum3",
    "artmuseum",
    "amap",
    "chinatravel",
    "osm",
)

_SYSTEM_PROMPT = (
    "你是旅游百科编辑，为中国景点地点写一句话中文简介。铁律："
    "只写广为人知的常识事实，不确定的年份/数字/排名/头衔一律不写、"
    "绝不编造；简介 40-70 字、单段、无换行无列表；"
    "若该名称完全无法辨认且无法安全描述，只回复 SKIP 两个字母；"
    "除简介正文外不要输出任何其他文字。"
)


# --- 产出校验（纯函数，写库前必过） ------------------------------------------


def _validate_intro(text: str, *, name_zh: str = "") -> str | None:
    """合格返回 None；否则返回拒绝原因码（too_short/too_long/no_cjk/
    meta_text/hedge/echo）。"""
    trimmed = text.strip()
    if len(trimmed) < 20:
        return "too_short"
    if len(trimmed) > 300:
        return "too_long"
    cjk = sum(1 for ch in trimmed if "一" <= ch <= "鿿")
    if cjk / len(trimmed) < 0.3:
        return "no_cjk"
    lowered = trimmed.lower()
    if "http" in lowered or "www" in lowered or "```" in trimmed:
        return "meta_text"
    if trimmed.startswith(("以下是", "这是")):
        return "meta_text"
    if any(h in lowered for h in ("作为ai", "抱歉", "无法确定", "我不知道")):
        return "hedge"
    if name_zh and trimmed == name_zh.strip():
        return "echo"
    return None


# --- 目标行选取 -------------------------------------------------------------


def _is_intro_empty(row: Poi) -> bool:
    return not (row.intro or "").strip()


def _source_rank():
    whens = [(Poi.source == src, rank) for rank, src in enumerate(_SOURCE_PRIORITY)]
    return case(*whens, else_=len(_SOURCE_PRIORITY))


def _query_targets(session, *, limit: int) -> list[Poi]:
    return (
        session.query(Poi)
        .filter(Poi.status == "active")
        .filter(or_(Poi.intro.is_(None), Poi.intro == ""))
        .order_by(_source_rank(), Poi.id)
        .limit(limit)
        .all()
    )


def select_targets(session_factory, *, limit: int = _DEFAULT_LIMIT) -> list[Poi]:
    """intro 为空且 active 的行，按 source 优先级 + id 排序后取 LIMIT 条。

    SQL 已滤 intro 空行；Python 侧再拦一遍，防查询改动漏带滤网。
    """
    with session_factory() as session:
        rows = _query_targets(session, limit=limit)
    return [r for r in rows if _is_intro_empty(r)]


# --- 单行处理 ---------------------------------------------------------------


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str
    category: str


def _messages(target: _Target) -> list[ChatMessage]:
    user = (
        f"城市：{target.city or '未知'}\n"
        f"名称：{target.name}\n"
        f"类别：{target.category or '未知'}\n"
        "请写这段简介。"
    )
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user),
    ]


def _write_intro(session_factory, poi_id, intro: str) -> bool:
    """独立短 session 单行写库；行消失或已被填则返回 False 不动库。"""
    with session_factory() as session:
        row = session.get(Poi, poi_id)
        if row is None or not _is_intro_empty(row):
            return False
        row.intro = intro
        row.intro_source = "llm"
        session.commit()
        return True


async def _process_row(
    adapter, session_factory, target: _Target, sem: asyncio.Semaphore, stats: dict
) -> None:
    if not target.name:
        # 无名称没法提问；罕见（种子层就滤过空名），计 skipped
        stats["skipped"] += 1
        return
    async with sem:
        try:
            result = await adapter.chat(
                _messages(target), temperature=0.3, max_tokens=_MAX_TOKENS
            )
        except Exception:
            # LLMError/超时/其它异常都只计数，继续下一条
            stats["errors"] += 1
            return
    stats["tokens_in"] += result.tokens_in
    stats["tokens_out"] += result.tokens_out
    # SKIP 前缀判定（探针：模型常带 "\\n\\n(Note: ...)" 尾巴）
    if result.content.strip().upper().startswith("SKIP"):
        stats["skipped"] += 1
        return
    reason = _validate_intro(result.content, name_zh=target.name)
    if reason is not None:
        stats["rejected"] += 1
        stats["rejected_by_reason"][reason] = (
            stats["rejected_by_reason"].get(reason, 0) + 1
        )
        return
    if not _write_intro(session_factory, target.poi_id, result.content.strip()):
        # 行被抢先填过/消失——不算 filled 也不算错误，静默放弃
        return
    stats["filled"] += 1


async def backfill_intro_llm(
    session_factory,
    adapter,
    *,
    limit: int = _DEFAULT_LIMIT,
    concurrency: int = 4,
) -> dict:
    """有界并发回填；每条完成即写库，串行语义下的只填空约束不破。"""
    concurrency = max(1, min(concurrency, _MAX_CONCURRENCY))
    stats = {
        "targets": 0,
        "filled": 0,
        "skipped": 0,
        "rejected": 0,
        "rejected_by_reason": {},
        "errors": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    targets = [
        _Target(
            poi_id=r.id,
            name=(r.name_zh or "").strip(),
            city=(r.city or "").strip(),
            category=(r.category or "").strip(),
        )
        for r in select_targets(session_factory, limit=limit)
    ]
    stats["targets"] = len(targets)
    sem = asyncio.Semaphore(concurrency)
    await asyncio.gather(
        *(_process_row(adapter, session_factory, t, sem, stats) for t in targets)
    )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int = _DEFAULT_LIMIT) -> None:
    """只数目标行 + 打印前 5 个样例，不调 API 不写库。"""
    rows = select_targets(session_factory, limit=limit)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))
    for row in rows[:5]:
        print(
            json.dumps(
                {
                    "source": row.source,
                    "city": row.city,
                    "name": row.name_zh,
                    "category": row.category,
                },
                ensure_ascii=True,
            )
        )


def _ping(factory) -> bool:
    try:
        with factory() as session:
            session.query(Poi.id).first()
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill empty POI intros via Zhipu GLM "
            "(fill-empty-only, validated before write)"
        )
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument(
        "--concurrency", type=int, default=4, help="parallel LLM calls, max 8"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="count + 5 samples, no API no write"
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
                    "error": "database unreachable - "
                    "start docker db (docker compose up -d db) "
                    "or check database_url"
                },
                ensure_ascii=True,
            )
        )
        return 1
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    settings = get_settings()
    if not settings.glm_api_key:
        print(
            json.dumps(
                {"error": "glm_api_key is empty - set it in .env"}, ensure_ascii=True
            )
        )
        return 1
    # 直接用 glm_* 字段构造 adapter；LLM_BACKEND 只管 agent 运行时。
    # model 钉死 flash 档：批处理不跟主模型升档烧贵池子
    adapter = ZhipuGLMAdapter(
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
        model=settings.glm_model_flash,
        timeout_seconds=settings.glm_timeout_seconds,
    )
    stats = asyncio.run(
        backfill_intro_llm(
            factory, adapter, limit=args.limit, concurrency=args.concurrency
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
