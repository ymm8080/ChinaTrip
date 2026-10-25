"""双语 P1：_en 列翻译回填作业（DESIGN language_dual_system §5.3）。

把 pois/restaurants 已有的中文文案译成英文并写 *_en 列——**译不写**：
只翻库里已有文本（intro/address/review_tags/name），绝不生成新事实；
铁律「只填空」：*_en 已有值绝不被覆盖（独立短 session 逐列复查）。
评审摘要/简介等描述性生成走各自原作业；本作业是纯翻译，符合
「事实类不编造」边界。

规格照抄 backfill_intro_llm 实测硬规格（2026-10-24 探针）：
  * glm-5.3-flash 思考模型，max_tokens 一律 1024；
  * 模型对翻不了的行常回 "SKIP\\n\\n(Note: ...)"——SKIP 前缀判定；
  * 单条 wall ~8s → Semaphore 有界并发（默认 4、上限 8）；
  * 每条完成即独立短 session 写库。

校验（写库前必过）：非空、Latin 主体、非原文复读、无 meta/客套、
长度界。review_tags（JSONB 中文标签数组）逐条翻译后同型写回。

用法：
    python -m app.jobs.backfill_en_columns [--table pois] [--limit 200]
        [--concurrency 4] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from typing import Any

from app.models import Poi, Restaurant

_MAX_TOKENS = 1024
_MAX_CONCURRENCY = 8

_SYSTEM_PROMPT = (
    "你是旅游数据翻译员，把中文旅游文案译成地道的英文。铁律："
    "只翻译给定文本，不添加任何新信息、不意译扩写；"
    "专有地名用通行罗马拼写（如 故宫=Palace Museum, 外滩=Bund）；"
    "若文本完全是专名/代号无法有意义翻译，只回复 SKIP 两个字母；"
    "除译文外不要输出任何其他文字。"
)

# 翻译目标：列名 → (源列属性名, 类型)
#   text = 普通文本；tags = JSONB 中文标签数组逐条译
FIELD_SPECS: dict[str, dict[str, tuple[str, str]]] = {
    "pois": {
        "name_en": ("name_zh", "text"),
        "intro_en": ("intro", "text"),
        "address_en": ("address", "text"),
        "review_tags_en": ("review_tags", "tags"),
        # P1.5：口碑摘要 EN（源=中文蒸馏摘要，译不写）
        "review_summary_en": ("review_summary", "text"),
        # P1.6：营业时间 EN（"周一闭馆"类中文表述，卡片直展）
        "opening_hours_en": ("opening_hours", "text"),
    },
    "restaurants": {
        "name_en": ("name_zh", "text"),
        "intro_en": ("intro", "text"),
        "address_en": ("address", "text"),
        # P1.5：与 pois 对称 + 菜系/招牌菜
        "review_tags_en": ("review_tags", "tags"),
        "opening_hours_en": ("opening_hours", "text"),
        "cuisine_en": ("cuisine", "text"),
        "signature_dishes_en": ("signature_dishes", "tags"),
    },
}


def _latin_ratio(text: str) -> float:
    if not text:
        return 0.0
    latin = sum(1 for ch in text if ch.isascii() and (ch.isalpha() or ch.isspace()))
    return latin / max(len(text), 1)


def validate_translation(text: str, *, source: str) -> str | None:
    """合格返回 None；否则拒绝原因码（too_short/no_latin/echo/meta）。"""
    trimmed = (text or "").strip()
    if len(trimmed) < 2:
        return "too_short"
    if len(trimmed) > 600:
        return "too_long"
    if _latin_ratio(trimmed) < 0.6:
        return "no_latin"
    lowered = trimmed.lower()
    meta_marks = ("http", "```", "以下是", "this is a translation")
    if any(m in lowered for m in meta_marks):
        return "meta"
    src = (source or "").strip()
    if src and trimmed.lower() == src.lower():
        return "echo"
    # 中文占比过高说明模型回的是中文原文
    cjk = sum(1 for ch in trimmed if "一" <= ch <= "鿿")
    if src and cjk > len(src) * 0.5:
        return "not_translated"
    return None


def validate_hours_en(text: str, *, source: str) -> str | None:
    """hours 专用验收（宽松于通用闸门）。

    硬关：无 CJK（防回中文）、拉丁主体、时间数字保真（@HH:MM 集合
    一致，防 LLM 改错时刻——真实危害远大于长度）。
    长度 2-300（原 600 对 hours 常态过松、20 过严）。
    """
    t = (text or "").strip()
    if not (2 <= len(t) <= 300):
        return "too_short" if len(t) < 2 else "too_long"
    if _CJK(t):
        return "no_latin"
    # hours 含大量数字/时间标点：按"非 CJK 即接受"口径（拉丁比率失真）
    src_times = set(re.findall(r"\d{1,2}:\d{2}", source or ""))
    out_times = set(re.findall(r"\d{1,2}:\d{2}", t))
    if src_times and src_times != out_times:
        return "time_drift"
    lowered = t.lower()
    if "http" in lowered or "```" in t:
        return "meta"
    return None


def parse_tags_json(text: str | None) -> list[str] | None:
    """LLM 回的标签数组 → list[str]；非法/空返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    try:
        arr = json.loads(t)
    except (ValueError, TypeError):
        return None
    if not isinstance(arr, list):
        return None
    items = [str(x).strip() for x in arr if str(x).strip()]
    if not items or len(items) > 12:
        return None
    if any(validate_translation(x, source="tag") is not None for x in items):
        return None
    return items


_DAY_EN = {
    "一": "Monday",
    "二": "Tuesday",
    "三": "Wednesday",
    "四": "Thursday",
    "五": "Friday",
    "六": "Saturday",
    "日": "Sunday",
    "天": "Sunday",
}  # 用户定案（2026-10-25）：不用简写，全称


# 模板可覆盖的中文残句判定（转换后仍含 CJK → 走 LLM 兜底）
def _CJK(t: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in t)


def template_hours_en(text: str | None) -> str | None:
    """中文营业时间 → EN 模板转换（确定性，数字零风险）。

    用户定案用词（2026-10-25）：周一闭馆 → "Monday Closed"；
    周一至周日 → "Monday–Sunday"。转换后仍含中文 → None（调用方走 LLM）。
    """
    if not text:
        return None
    import re as _re

    out = _re.sub(
        r"[周星][期]?([一二三四五六日天])", lambda m: _DAY_EN[m.group(1)], text
    )
    out = out.replace("至", "–").replace("—", "–")
    out = out.replace("闭馆", " Closed").replace("不开放", " Closed")
    out = out.replace("法定节假日除外", "except public holidays")
    out = out.replace("法定节假日", "public holidays")
    out = out.replace("全天", " All day")
    out = out.replace("；", "; ").replace("，", ", ")
    out = out.replace("（）", "").replace("()", "")
    out = _re.sub(r"  +", " ", out).strip()
    if _CJK(out):
        return None
    return out


def _messages(kind: str, source: Any, name: str) -> list:
    from app.services.llm.base import ChatMessage

    if kind == "tags":
        user = (
            f"地点：{name}\n"
            f"把以下中文点评标签数组译成英文数组（JSON 数组输出，"
            f"条数一一对应）：{json.dumps(source, ensure_ascii=False)}"
        )
    else:
        user = f"地点：{name}\n把以下中文译成英文：{source}"
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user),
    ]


def select_targets(session_factory, table: str, *, limit: int) -> list[Any]:
    """目标行：任一目标 _en 列为空且对应源列非空的 active 行。

    selectinload 无必要——单表直查；排序 name_en 优先（名称最值钱）。
    """
    model = Poi if table == "pois" else Restaurant
    specs = FIELD_SPECS[table]
    from sqlalchemy import or_

    conds = []
    for en_col, (src_col, _kind) in specs.items():
        conds.append(
            getattr(model, en_col).is_(None) & getattr(model, src_col).isnot(None)
        )
    with session_factory() as session:
        rows = (
            session.query(model)
            .filter(or_(*conds), (model.status.is_(None)) | (model.status == "active"))
            .order_by(model.name_en.is_(None), model.rating_count.desc().nullslast())
            .limit(limit)
            .all()
        )
    return rows


def _write_row(session_factory, model, row_id, updates: dict) -> bool:
    """独立短 session 逐列只填空写回；返回是否实际写入。"""
    if not updates:
        return False
    with session_factory() as session:
        row = session.get(model, row_id)
        if row is None:
            return False
        touched = False
        for col, val in updates.items():
            if getattr(row, col) is None and val is not None:
                setattr(row, col, val)
                touched = True
        if touched:
            session.commit()
        return touched


async def _process_row(
    adapter, session_factory, row: Any, table: str, sem, stats: dict
) -> None:
    model = Poi if table == "pois" else Restaurant
    specs = FIELD_SPECS[table]
    updates: dict = {}
    name = (row.name_zh or "").strip()
    # VARCHAR 列长度预检：超列限的译文拒收（StringDataRightTruncation
    # 单行掀整批的实锤 2026-10-25；Text/JSONB 列 length 为 None 不设限）
    col_limit = {
        en_col: getattr(getattr(model, en_col).type, "length", None) for en_col in specs
    }

    def _fits(col: str, text: str) -> bool:
        limit = col_limit[col]
        return limit is None or len(text) <= limit

    async with sem:
        for en_col, (src_col, kind) in specs.items():
            if getattr(row, en_col) is not None:
                continue  # 只填空
            source = getattr(row, src_col)
            if source is None or (isinstance(source, list) and not source):
                continue
            if kind == "tags":
                source = [str(t).strip() for t in source if str(t).strip()]
                if not source:
                    continue
            if en_col == "opening_hours_en":
                # 模板优先（确定性零成本）；残句才走 LLM（v1.0 §5.2 既定）
                templated = template_hours_en(str(source))
                if templated:
                    if _fits(en_col, templated):
                        updates[en_col] = templated
                        stats["template"] += 1
                    else:
                        stats["rejected"] += 1
                    continue
            try:
                result = await adapter.chat(
                    _messages(kind, source, name or "未知"),
                    temperature=0.2,
                    max_tokens=_MAX_TOKENS,
                )
            except Exception:
                stats["errors"] += 1
                continue
            stats["tokens_in"] += result.tokens_in
            stats["tokens_out"] += result.tokens_out
            content = result.content.strip()
            if content.upper().startswith("SKIP"):
                stats["skipped"] += 1
                continue
            if kind == "tags":
                parsed = parse_tags_json(content)
                if parsed is None:
                    stats["rejected"] += 1
                    continue
                updates[en_col] = parsed
            elif en_col == "opening_hours_en":
                reason = validate_hours_en(content, source=str(source))
                if reason is not None:
                    stats["rejected"] += 1
                    stats["rejected_by_reason"][reason] = (
                        stats["rejected_by_reason"].get(reason, 0) + 1
                    )
                    continue
                updates[en_col] = content
            else:
                reason = validate_translation(content, source=str(source))
                if reason is not None:
                    stats["rejected"] += 1
                    stats["rejected_by_reason"][reason] = (
                        stats["rejected_by_reason"].get(reason, 0) + 1
                    )
                    continue
                if not _fits(en_col, content):
                    # 列装不下（如 address_en VARCHAR(200)）→ 拒收留空回退中文
                    stats["rejected"] += 1
                    continue
                updates[en_col] = content
    if updates:
        # 单行写库隔离：一行异常只计 errors，绝不掀翻整批
        try:
            if _write_row(session_factory, model, row.id, updates):
                stats["rows_filled"] += 1
                stats["fields_filled"] += len(updates)
        except Exception:
            stats["errors"] += 1


async def backfill_en(
    session_factory,
    adapter,
    *,
    table: str = "pois",
    limit: int = 200,
    concurrency: int = 4,
) -> dict:
    if table not in FIELD_SPECS:
        raise ValueError(f"unknown table: {table}")
    concurrency = max(1, min(concurrency, _MAX_CONCURRENCY))
    rows = select_targets(session_factory, table, limit=limit)
    stats: dict = {
        "table": table,
        "targets": len(rows),
        "rows_filled": 0,
        "fields_filled": 0,
        "skipped": 0,
        "rejected": 0,
        "rejected_by_reason": {},
        "errors": 0,
        "template": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    sem = asyncio.Semaphore(concurrency)
    await asyncio.gather(
        *(_process_row(adapter, session_factory, r, table, sem, stats) for r in rows)
    )
    return stats


def _ping(factory) -> bool:
    try:
        with factory() as session:
            session.query(Poi.id).first()
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill *_en columns by translating existing zh text"
    )
    parser.add_argument("--table", choices=sorted(FIELD_SPECS), default="pois")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=4, help="并发，上限 8")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from app.config import get_settings
    from app.db import get_session_factory

    factory = get_session_factory()
    if not _ping(factory):
        print(json.dumps({"error": "database unreachable"}))
        return 1
    if args.dry_run:
        rows = select_targets(factory, args.table, limit=args.limit)
        print(json.dumps({"dry_run": True, "targets": len(rows)}))
        for r in rows[:5]:
            print(json.dumps({"name": r.name_zh, "has_intro": bool(r.intro)}))
        return 0
    settings = get_settings()
    if not settings.glm_api_key:
        print(json.dumps({"error": "glm_api_key is empty - set it in .env"}))
        return 1
    from app.services.llm.zhipu import ZhipuGLMAdapter

    adapter = ZhipuGLMAdapter(
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
        model=settings.glm_model_flash,
        timeout_seconds=settings.glm_timeout_seconds,
    )
    stats = asyncio.run(
        backfill_en(
            factory,
            adapter,
            table=args.table,
            limit=args.limit,
            concurrency=args.concurrency,
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
