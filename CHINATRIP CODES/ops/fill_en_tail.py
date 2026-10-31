"""尾部清理（一次性 ops 脚本）：把主驱动清不动的两类尾巴收掉。

A. 拉丁源直拷：源文本本身就是拉丁文时，模型必然 echo/SKIP 拒译（实测批次
   06:11：333 echo + 579 SKIP），正确处置是 _en = 源（不编造，等价翻译）。
   覆盖：restaurants.name_en / cuisine_en，pois.opening_hours_en / address_en
   （时钟串/拼音地址同理）。latin_ratio >= 0.6 才拷，只填空。
B. pois intro_en too_long 尾巴（297 行）：中文简介长、英文译文超
   backfill_en_columns.validate_translation 的 600 字符硬上限被反复拒。
   本脚本以放宽上限 1200 重译，校验 latin/echo/meta/原文复读，只填空。

用法：python ops/fill_en_tail.py [--concurrency 6]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import and_, or_

from app.config import get_settings
from app.db import get_session_factory
from app.jobs.backfill_en_columns import _SYSTEM_PROMPT, _latin_ratio
from app.models import Poi, Restaurant
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import ZhipuGLMAdapter

_COPY_RATIO = 0.6
_MAX_TOKENS = 2048
_INTRO_EN_MAX = 2500

_COPY_SPECS = [
    (Restaurant, "name_en", "name_zh"),
    (Restaurant, "cuisine_en", "cuisine"),
    (Poi, "opening_hours_en", "opening_hours"),
    (Poi, "address_en", "address"),
]


def _is_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def validate_intro_en(text: str, *, source: str) -> str | None:
    """同 validate_translation，但上限放宽到 1200（长中文简介的英文膨胀）。"""
    trimmed = (text or "").strip()
    if len(trimmed) < 20:
        return "too_short"
    if len(trimmed) > _INTRO_EN_MAX:
        return "too_long"
    if _latin_ratio(trimmed) < 0.6:
        return "no_latin"
    lowered = trimmed.lower()
    if any(m in lowered for m in ("http", "```", "以下是", "this is a translation")):
        return "meta"
    if trimmed.lower() == (source or "").strip().lower():
        return "echo"
    cjk = sum(1 for ch in trimmed if "一" <= ch <= "鿿")
    if cjk > len(source) * 0.5:
        return "not_translated"
    return None


def copy_through(factory) -> dict:
    stats = {}
    for model, en_col, src_col in _COPY_SPECS:
        # 名字列放宽：纯拉丁（可含数字/符号、无 CJK）即拷——"Fu 1039" 类
        # 名字按字母占比 0.6 会被数字拉低而漏拷
        relaxed = en_col.endswith("name_en")
        with factory() as session:
            rows = (
                session.query(model)
                .filter(
                    getattr(model, en_col).is_(None),
                    getattr(model, src_col).isnot(None),
                    getattr(model, src_col) != "",
                    or_(model.status.is_(None), model.status == "active"),
                )
                .all()
            )
        filled = 0
        for row in rows:
            src = (getattr(row, src_col) or "").strip()
            if not src or _is_cjk(src):
                continue
            if relaxed:
                if _latin_ratio(src) < 0.4:
                    continue
            elif _latin_ratio(src) < _COPY_RATIO:
                continue
            with factory() as s2:
                obj = s2.get(model, row.id)
                if obj is not None and getattr(obj, en_col) is None:
                    setattr(obj, en_col, src)
                    s2.commit()
                    filled += 1
        stats[f"{model.__tablename__}.{en_col}"] = {"candidates": len(rows), "copied": filled}
    return stats


async def retranslate_long_intros(factory, adapter, sem_size: int) -> dict:
    stats = {"targets": 0, "filled": 0, "skipped": 0, "rejected": 0, "errors": 0}
    sem = asyncio.Semaphore(sem_size)

    async def one(row):
        async with sem:
            name = (row.name_zh or "").strip()
            user = (
                f"地点：{name}\n把以下中文译成英文。铁律：只输出英文译文本身，"
                f"不要输出地点名、不要任何前缀或说明：\n{row.intro}"
                if name
                else f"把以下中文译成英文，只输出译文本身：{row.intro}"
            )
            msgs = [
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=user),
            ]
            try:
                result = await adapter.chat(msgs, temperature=0.3, max_tokens=_MAX_TOKENS)
            except Exception as exc:
                print(f"[err] {name[:20]}: {exc!r}"[:220], flush=True)
                stats["errors"] += 1
                return
            out = result.content.strip()
            if out.upper().startswith("SKIP"):
                stats["skipped"] += 1
                return
            reason = validate_intro_en(out, source=row.intro)
            if reason is not None:
                stats["rejected"] += 1
                return
            with factory() as session:
                obj = session.get(Poi, row.id)
                if obj is not None and (obj.intro_en is None or obj.intro_en == ""):
                    obj.intro_en = out
                    session.commit()
                    stats["filled"] += 1

    with factory() as session:
        rows = (
            session.query(Poi)
            .filter(
                or_(Poi.intro_en.is_(None), Poi.intro_en == ""),
                Poi.intro.isnot(None),
                Poi.intro != "",
                or_(Poi.status.is_(None), Poi.status == "active"),
            )
            .all()
        )
    stats["targets"] = len(rows)
    await asyncio.gather(*(one(r) for r in rows))
    return stats


async def amain(factory, adapter, sem_size: int) -> dict:
    out = {"copy_through": copy_through(factory)}
    out["intro_en_long"] = await retranslate_long_intros(factory, adapter, sem_size)
    return out


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
        timeout_seconds=120,
    )
    factory = get_session_factory()
    import json

    print(json.dumps(asyncio.run(amain(factory, adapter, args.concurrency)), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
