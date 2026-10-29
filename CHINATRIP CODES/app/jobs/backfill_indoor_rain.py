"""indoor / rain_ok 批量回填作业（DESIGN §3.2 B2，2026-10-25）。

天气感知重排（weather × rain_ok）的数据基础。三层模式与
backfill_best_visit 同款，本作业提供两层：

  --stage heuristic  纯本地规则（名称/类别关键词 → yes/no/partial），零成本
  --stage llm        启发式 yes/no 直填（零成本），partial/未命中的行走 LLM
                     （智谱 flash 档，成本控制；规格同 backfill_intro_llm：
                     max_tokens=1024 防 thinking 吃光额度）

铁律「只填空」：indoor/rain_ok 已有值绝不被覆盖（llm 层逐列复查）。
rain_ok 派生自 indoor（indoor=yes → rain_ok=yes；no → no；
partial → partial）——雨天感知只吃这一个信号，简单可解释。

用法：
    python -m app.jobs.backfill_indoor_rain --stage heuristic [--limit 500]
    python -m app.jobs.backfill_indoor_rain --stage llm [--limit 500]
        [--concurrency 4]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from app.models import Poi

logger = logging.getLogger(__name__)

# 名称/类别关键词 → indoor 判定（国内场馆命名惯例，heuristic 层够用）
_INDOOR_MARKS = (
    "博物馆",
    "博物院",
    "美术馆",
    "艺术馆",
    "科技馆",
    "纪念馆",
    "展览馆",
    "图书馆",
    "剧院",
    "剧场",
    "音乐厅",
    "商场",
    "购物中心",
    "水族馆",
    "海洋馆",
    "美术馆",
    "天文馆",
    "规划馆",
    "体验馆",
)
_OUTDOOR_MARKS = (
    "山",
    "湖",
    "江",
    "河",
    "海",
    "滩",
    "岛",
    "峡谷",
    "草原",
    "湿地",
    "公园",
    "广场",
    "步行街",
    "夜市",
    "古镇",
    "古街",
    "老街",
    "景区",
    "瀑布",
    "温泉",
    "滑雪场",
    "海滩",
    "沙漠",
    "森林",
    "竹海",
    "溶洞",
)
# 混合体（大部分露天但有室内环节）
_PARTIAL_MARKS = ("乐园", "迪士尼", "欢乐谷", "动物园", "植物园", "度假区", "影视城")


def classify_indoor(name: str | None, category: str | None) -> str | None:
    """名称/类别关键词启发式（纯函数）：yes / no / partial / None 未判定。"""
    cat = category or ""
    # 高德类别「风景名胜/自然景观/公园」等本身就是露天语义
    if any(m in cat for m in ("风景名胜", "自然", "公园", "海滩", "山")):
        return "no"
    hay = f"{name or ''} {cat}"
    if not hay.strip():
        return None
    if any(m in hay for m in _INDOOR_MARKS):
        return "yes"
    if any(m in hay for m in _PARTIAL_MARKS):
        return "partial"
    if any(m in hay for m in _OUTDOOR_MARKS):
        return "no"
    return None


def rain_ok_from_indoor(indoor: str | None) -> str | None:
    return indoor  # 派生规则 v0：同值（yes→适合雨天；no→露天；partial→部分）


def backfill(
    rows: list[Any],
    *,
    stage: str = "heuristic",
    writer=None,
) -> dict:
    """rows = ORM Poi 行；writer(row, indoor, rain_ok) 落库（作业侧注入，
    便于测试）。heuristic 层零网络零 LLM。"""
    stats = {"scanned": len(rows), "filled": 0, "skipped_existing": 0, "unmatched": 0}
    for row in rows:
        if getattr(row, "indoor", None) or getattr(row, "rain_ok", None):
            stats["skipped_existing"] += 1
            continue
        verdict = classify_indoor(row.name_zh, row.category)
        if verdict is None:
            stats["unmatched"] += 1
            continue
        if writer is not None:
            writer(row, verdict, rain_ok_from_indoor(verdict))
        stats["filled"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回填 indoor/rain_ok（只填空）")
    parser.add_argument("--stage", choices=["heuristic", "llm"], default="heuristic")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=4, help="llm 层并发，上限 8")
    args = parser.parse_args(argv)
    if args.stage == "llm":
        return _main_llm(args)
    return _main_heuristic(args)


# --- llm 层（规格照抄 backfill_intro_llm：flash 档/只填空/有界并发） ----------

_MAX_TOKENS = 1024  # 思考模型：额度不足时 thinking 吃光 content 返回空串
_MAX_CONCURRENCY = 8
_LLM_SYSTEM_PROMPT = (
    "你是旅游数据标注员，判断中国景点/场馆主要在室内还是露天。"
    "只回复一个词：室内、露天、混合；名称完全无法辨认则只回复 SKIP。"
    "除该词外不要输出任何其他文字。"
)


def parse_verdict(text: str | None) -> str | None:
    """LLM 产出 → yes/no/partial；SKIP/空/其它一律 None（调用方计 rejected）。"""
    t = (text or "").strip()
    if not t:
        return None
    if t.upper().startswith("SKIP"):
        return "skip"
    # 前缀判定：模型偶尔带尾注（探针见 backfill_intro_llm docstring）
    if t.startswith("室内"):
        return "yes"
    if t.startswith("露天"):
        return "no"
    if t.startswith("混合"):
        return "partial"
    return None


def _llm_messages(name: str, city: str | None, category: str | None) -> list:
    from app.services.llm.base import ChatMessage

    return [
        ChatMessage(role="system", content=_LLM_SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=f"城市：{city or '未知'}\n名称：{name}\n类别：{category or '未知'}",
        ),
    ]


def _write_columns(
    session_factory, poi_id: int, indoor: str | None, rain: str | None
) -> bool:
    """独立短 session 逐列只填空；行消失或两列均已填返回 False 不动库。"""
    with session_factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return False
        touched = False
        if indoor and row.indoor is None:
            row.indoor = indoor
            touched = True
        if rain and row.rain_ok is None:
            row.rain_ok = rain
            touched = True
        if touched:
            session.commit()
        return touched


async def _process_row(adapter, session_factory, row: Poi, sem, stats: dict) -> None:
    """启发式 yes/no 直填（零成本）；partial/未命中走 LLM。写库前逐列复查。"""
    heuristic = classify_indoor(row.name_zh, row.category)
    verdict = heuristic if heuristic in ("yes", "no") else None
    if verdict is None:
        if not (row.name_zh or "").strip():
            stats["skipped"] += 1
            return
        async with sem:
            try:
                result = await adapter.chat(
                    _llm_messages(row.name_zh, row.city, row.category),
                    temperature=0.3,
                    max_tokens=_MAX_TOKENS,
                )
            except Exception:
                stats["errors"] += 1
                return
        stats["tokens_in"] += result.tokens_in
        stats["tokens_out"] += result.tokens_out
        verdict = parse_verdict(result.content)
        if verdict in (None, "skip"):
            stats["rejected"] += 1
            return
    indoor = row.indoor if row.indoor is not None else verdict
    rain = row.rain_ok if row.rain_ok is not None else rain_ok_from_indoor(verdict)
    if _write_columns(session_factory, row.id, indoor, rain):
        stats["filled"] += 1
    else:
        stats["skipped_existing"] += 1


async def backfill_indoor_llm(
    session_factory, adapter, *, limit: int = 500, concurrency: int = 4
) -> dict:
    """indoor/rain_ok 任一为空且 active 的行；有界并发、每行独立写库。"""
    from sqlalchemy import or_

    concurrency = max(1, min(concurrency, _MAX_CONCURRENCY))
    with session_factory() as session:
        rows = (
            session.query(Poi)
            .filter(
                or_(Poi.indoor.is_(None), Poi.rain_ok.is_(None)),
                (Poi.status.is_(None)) | (Poi.status == "active"),
            )
            .limit(limit)
            .all()
        )
    stats: dict = {
        "targets": len(rows),
        "filled": 0,
        "skipped": 0,
        "skipped_existing": 0,
        "rejected": 0,
        "errors": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    sem = asyncio.Semaphore(concurrency)
    await asyncio.gather(
        *(_process_row(adapter, session_factory, r, sem, stats) for r in rows)
    )
    return stats


def _main_llm(args) -> int:
    from app.config import get_settings
    from app.db import get_session_factory

    try:
        factory = get_session_factory()
        with factory() as session:
            session.query(Poi.id).first()
    except Exception:
        print(json.dumps({"error": "database unreachable"}))
        return 1
    settings = get_settings()
    if not settings.glm_api_key:
        print(json.dumps({"error": "glm_api_key is empty - set it in .env"}))
        return 1
    from app.services.llm.zhipu import ZhipuGLMAdapter

    # 批处理钉死 flash 档（同 backfill_intro_llm：不跟主模型升档）
    adapter = ZhipuGLMAdapter(
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
        model=settings.glm_model_flash,
        timeout_seconds=settings.glm_timeout_seconds,
    )
    stats = asyncio.run(
        backfill_indoor_llm(
            factory, adapter, limit=args.limit, concurrency=args.concurrency
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


def _main_heuristic(args) -> int:
    from app.db import get_session_factory

    try:
        factory = get_session_factory()
    except Exception:
        print(json.dumps({"error": "database unreachable"}))
        return 1
    from sqlalchemy import or_

    with factory() as session:
        rows = (
            session.query(Poi)
            .filter(
                or_(Poi.indoor.is_(None), Poi.rain_ok.is_(None)),
                (Poi.status.is_(None)) | (Poi.status == "active"),
            )
            .limit(args.limit)
            .all()
        )

        def writer(row: Any, indoor: str, rain: str) -> None:
            row.indoor = indoor
            row.rain_ok = rain

        stats = backfill(rows, stage=args.stage, writer=writer)
        session.commit()
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
