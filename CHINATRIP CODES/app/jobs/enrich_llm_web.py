"""POI 富化 LLM+联网试点：suggested_duration_min + name_aliases。

需求（2026-10-25 用户拍板）：列要填满，LLM 只当"先联网查证再填数"的
工人，绝不凭记忆编造。探针实测：coding 端点 chat completions 支持
tools=[{"type":"web_search","web_search":{"enable":True}}]，服务端先
搜后答，走 START PLAN token。

试点范围：active 且 suggested_duration_min 为空，按
unesco/5a/amap 优先 + rating 降序——规划器 top_pois_in_city 最先
挑出来的行。

铁律：
  * 只填空——写库前复查目标列仍为空才 UPDATE；
  * duration 必须是 15-600 的整数，模型填不出可靠值就跳过该列；
  * aliases 逐个 2-40 字、剔除主名本身与含 URL/邮箱项、去重、最多 5 个；
  * 来源标记 duration_source='llm_web'（aliases 无 source 列，靠作业日志溯源）；
  * API 429/5xx 先退避重试（账户与线上规划器共用，实测并发即 429），耗尽后
    计数不中断，error_kinds 带 HTTP 状态码。

用法：
    python -m app.jobs.enrich_llm_web [--limit 100] [--concurrency 4] [--dry-run]

2026-10-25 实测：coding 端点静默忽略 web_search（模型自述无搜索，
40 目标仅 1 填上、29 诚实回 null；详见 enrich_ctrip_detail.py 头注）。
本作业暂勿排期，待端点支持联网再启用。
"""

import argparse
import asyncio
import json
import random
import re
import sys
import time
from typing import NamedTuple

import httpx
from sqlalchemy import case

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.poi_classify import duration_upgradable

_DEFAULT_LIMIT = 100
_MAX_TOKENS = 1024
_MAX_CONCURRENCY = 4
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
_DURATION_MIN, _DURATION_MAX = 15, 600
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)
_MAX_ATTEMPTS = 6

_SYSTEM_PROMPT = (
    "你是旅游数据编辑。铁律：只依据联网搜索结果作答，搜不到可靠依据的"
    "数字一律填 null，绝不凭记忆编造；输出必须是纯 JSON，不要任何解释文字。"
)

_USER_TMPL = (
    "景点名称：{name}\n城市：{city}\n类别：{category}\n"
    "请联网搜索该景点的官方或权威游玩信息，回答两个字段：\n"
    '1. "duration_min"：建议游玩时长（分钟，纯整数；搜索结果没有可靠'
    "依据就填 null）\n"
    '2. "aliases"：该景点的常见别名/曾用名/通用叫法（JSON 字符串数组，'
    "最多 5 个，不含主名本身；没有就空数组）\n"
    '只输出 JSON：{{"duration_min": <整数或null>, "aliases": ["…"], '
    '"evidence": "<来源要点，≤50字，没有依据就空串>"}}'
)


def _validate_duration(v) -> int | None:
    """合格返回 int（15-600），否则 None。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    iv = int(v)
    if iv != v or not (_DURATION_MIN <= iv <= _DURATION_MAX):
        return None
    return iv


def _clean_aliases(raw, name_zh: str) -> list[str]:
    """过滤为安全别名列表：去主名/URL/邮箱/超长项，去重，截 5 个。"""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for a in raw:
        if not isinstance(a, str):
            continue
        a = a.strip()
        if not (2 <= len(a) <= 40) or a == (name_zh or "").strip():
            continue
        low = a.lower()
        if "http" in low or "@" in a or a in out:
            continue
        out.append(a)
        if len(out) >= 5:
            break
    return out


def _extract_json(text: str) -> dict | None:
    """剥掉可能的 ```json 围栏后解析；失败返回 None。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


# --- 目标行选取 -------------------------------------------------------------


def _source_rank():
    whens = [(Poi.source == src, rank) for rank, src in enumerate(_SOURCE_PRIORITY)]
    return case(*whens, else_=len(_SOURCE_PRIORITY))


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(Poi.status == "active", Poi.name_aliases.is_(None))
            .order_by(Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str
    category: str


def _to_target(r: Poi) -> _Target:
    return _Target(
        r.id,
        (r.name_zh or "").strip(),
        (r.city or "").strip(),
        (r.category or "").strip(),
    )


# --- 单行处理 ---------------------------------------------------------------


def _chat_web(
    settings, *, name: str, city: str, category: str, timeout: float
) -> tuple[dict, dict]:
    """带 web_search 工具的一次调用，返回 (解析后的 dict, usage)（失败抛异常）。

    429/5xx 按 Retry-After 或指数退避重试（该 glm 账户与线上规划器共用，
    实测并发即触 429 code 1302）；usage 附带 retries 计数。
    """
    body = {
        "model": settings.glm_model_flash,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _USER_TMPL.format(
                    name=name, city=city or "未知", category=category or "未知"
                ),
            },
        ],
        "tools": [{"type": "web_search", "web_search": {"enable": True}}],
        "temperature": 0.1,
        "max_tokens": _MAX_TOKENS,
    }
    retries = 0
    for attempt in range(_MAX_ATTEMPTS):
        r = httpx.post(
            f"{settings.glm_base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {settings.glm_api_key}"},
            timeout=timeout,
        )
        if r.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
            retries += 1
            wait = r.headers.get("retry-after")
            try:
                delay = float(wait) if wait is not None else 0.0
            except ValueError:
                delay = 0.0
            if delay <= 0:
                delay = min(90.0, 2.0**attempt + random.random() * 2)
            time.sleep(delay)
            continue
        r.raise_for_status()
        payload = r.json()
        content = payload["choices"][0]["message"]["content"]
        data = _extract_json(content)
        if data is None:
            raise ValueError(f"non-JSON reply: {content[:80]!r}")
        usage = dict(payload.get("usage") or {})
        usage["retries"] = retries
        return data, usage
    raise RuntimeError("unreachable")


def _write(
    session_factory, poi_id, *, duration: int | None, aliases: list[str]
) -> tuple[bool, bool]:
    """独立短 session 只填空写库；返回 (duration_written, aliases_written)。"""
    with session_factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return False, False
        d_ok = a_ok = False
        # heuristic 地板可升级（2026-10-25 拍板），其它真值源只填空
        if duration is not None and duration_upgradable(row):
            row.suggested_duration_min = duration
            row.duration_source = "llm_web"
            d_ok = True
        if aliases and row.name_aliases is None:
            row.name_aliases = aliases
            a_ok = True
        session.commit()
        return d_ok, a_ok


async def _process_row(
    settings, factory, target: _Target, sem: asyncio.Semaphore, stats: dict
) -> None:
    if not target.name:
        stats["skipped"] += 1
        return
    async with sem:
        try:
            data, usage = await asyncio.to_thread(
                _chat_web,
                settings,
                name=target.name,
                city=target.city,
                category=target.category,
                timeout=settings.glm_timeout_seconds + 30,
            )
        except Exception as exc:
            stats["errors"] += 1
            kind = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                kind = f"HTTP{exc.response.status_code}"
            stats["error_kinds"][kind] = stats["error_kinds"].get(kind, 0) + 1
            return
    stats["tokens_in"] += int(usage.get("prompt_tokens") or 0)
    stats["tokens_out"] += int(usage.get("completion_tokens") or 0)
    stats["api_retries"] += int(usage.get("retries") or 0)
    duration = _validate_duration(data.get("duration_min"))
    aliases = _clean_aliases(data.get("aliases"), target.name)
    evidence = str(data.get("evidence") or "")[:50]
    if duration is None:
        stats["duration_no_data"] += 1
    if not aliases:
        stats["aliases_none"] += 1
    if duration is None and not aliases:
        return
    d_ok, a_ok = await asyncio.to_thread(
        _write, factory, target.poi_id, duration=duration, aliases=aliases
    )
    stats["duration_filled"] += int(d_ok)
    stats["aliases_filled"] += int(a_ok)
    if d_ok:
        stats["evidence_samples"].append(
            {
                "name": target.name,
                "city": target.city,
                "duration_min": duration,
                "aliases": aliases,
                "evidence": evidence,
            }
        )


async def enrich(session_factory, settings, *, limit: int, concurrency: int) -> dict:
    stats = {
        "targets": 0,
        "skipped": 0,
        "duration_filled": 0,
        "duration_no_data": 0,
        "aliases_filled": 0,
        "aliases_none": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "api_retries": 0,
        "errors": 0,
        "error_kinds": {},
        "evidence_samples": [],
    }
    targets = [_to_target(r) for r in select_targets(session_factory, limit=limit)]
    stats["targets"] = len(targets)
    sem = asyncio.Semaphore(max(1, concurrency))
    await asyncio.gather(
        *(_process_row(settings, session_factory, t, sem, stats) for t in targets)
    )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int) -> None:
    rows = select_targets(session_factory, limit=limit)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))
    for r in rows[:5]:
        print(
            json.dumps(
                {
                    "source": r.source,
                    "city": r.city,
                    "name": r.name_zh,
                    "rating": r.rating,
                },
                ensure_ascii=True,
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM+web enrich duration/aliases")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--concurrency", type=int, default=_MAX_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    settings = get_settings()
    if not settings.glm_api_key:
        print(json.dumps({"error": "glm_api_key is empty"}, ensure_ascii=True))
        return 1
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    stats = asyncio.run(
        enrich(factory, settings, limit=args.limit, concurrency=args.concurrency)
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
