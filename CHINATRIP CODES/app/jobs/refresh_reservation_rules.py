"""17 馆预约规则每周全量核对作业（用户拍板 2026-10-25：每周日晚上跑）。

zhipu web_search 逐馆核对官方口径（提前天数/放票时刻/渠道/外籍友好/
来源 URL），五关校验后三路输出：
① 快照 JSON 落 DESIGN/reservation_rules_snapshot_<日期>.json（可审计）；
② 与 RESERVATION_V0 的 diff 报告——名单本体是版本控制的代码，作业只
   报告不改码（规则变了由人评审后改 reservation_seeds.py）；
③ 表行刷新（覆盖语义）：pois.reservation_required=True、
   reservation_advance_days=天数、booking_url=官方来源 URL——预约规则
   会变，这类字段按最新官方口径覆盖是正确语义。
mock 后端跳过；单馆失败不影响其余（errors 计数）。
--with-visa 顺带对 240h 免签口岸数量做只读核对报告（不写码）。
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

_DESIGN = Path(__file__).resolve().parent.parent.parent / "DESIGN"

_SYSTEM_PROMPT = (
    "你是中国旅游景区预约规则核对员。只依据官方来源（景区官网、官方"
    "微信公众号/小程序公告、政府网站），给出该场馆当前实行的预约规则。"
    "不确定的字段给 null，禁止编造。只输出 JSON，无其他文字。"
)
_USER_TMPL = (
    "场馆：{name}（{city}）\n"
    "核对 2026 年当前官方预约规则，输出 JSON："
    '{{"advance_days": 提前天数int, "release": "放票时刻HH:MM或null", '
    '"channel": "官方渠道全称", "foreigner_friendly": "yes/no/partial", '
    '"note": "关键例外一句话", "source": "官方来源URL"}}'
)


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _gates(rule: dict) -> list[str]:
    """五关校验：天数域/时刻格式/渠道长度/来源 URL/备注长度。返回问题列表。"""
    bad: list[str] = []
    days = rule.get("advance_days")
    if not isinstance(days, int) or not 1 <= days <= 30:
        bad.append(f"advance_days 非法: {days!r}")
    release = rule.get("release")
    if release is not None:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(release))
        if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
            bad.append(f"release 非法: {release!r}")
    channel = rule.get("channel")
    if not isinstance(channel, str) or not 2 <= len(channel.strip()) <= 60:
        bad.append(f"channel 非法: {channel!r}")
    source = rule.get("source")
    if not isinstance(source, str) or not source.startswith(("http://", "https://")):
        bad.append(f"source 非 URL: {source!r}")
    note = rule.get("note")
    if note is not None and len(str(note)) > 100:
        bad.append("note 超长")
    return bad


def _check_one(
    settings, name: str, city: str, timeout: float
) -> tuple[dict | None, dict]:
    """带 web_search 的一次核对调用，返回 (规则dict|None, usage)。"""
    import httpx

    body = {
        "model": settings.glm_model_flash,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _USER_TMPL.format(name=name, city=city)},
        ],
        "tools": [{"type": "web_search", "web_search": {"enable": True}}],
        "temperature": 0.1,
        "max_tokens": 800,
    }
    r = httpx.post(
        f"{settings.glm_base_url}/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {settings.glm_api_key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    content = payload["choices"][0]["message"]["content"]
    return _extract_json(content), payload.get("usage") or {}


def _apply_db(factory, venue_name: str, rule: dict) -> bool:
    """表行刷新（覆盖语义）：按 name_zh 精确命中写三列。返回是否命中行。"""
    from app.models import Poi

    hit = False
    with factory() as session:
        rows = session.query(Poi).filter(Poi.name_zh == venue_name).all()
        for row in rows:
            row.reservation_required = True
            row.reservation_advance_days = int(rule["advance_days"])
            if rule.get("source"):
                row.booking_url = rule["source"]
            hit = True
        session.commit()
    return hit


def _visa_report(settings) -> dict:
    """免签口岸数量只读核对（不写码）：与 visa_check 快照对数。"""
    from app.services.itinerary.visa_check import VISA_POLICY

    expected = len(VISA_POLICY["entry_ports"])
    rule, _u = _check_one(
        settings,
        "中国 240 小时过境免签适用口岸总数（当前公告口径，只报数字）",
        "全国",
        settings.glm_timeout_seconds + 30,
    )
    reported = rule.get("advance_days") if rule else None
    return {
        "snapshot_ports": expected,
        "reported_ports": reported,
        "match": reported == expected,
        "hint": (
            None
            if reported == expected
            else "数量不一致——人工核对官方公告后更新 visa_check.py"
        ),
    }


def _get_settings():
    from app.config import get_settings

    return get_settings()


def _session_factory():
    from app.db import get_session_factory

    return get_session_factory()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="17 馆预约规则每周全量核对")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="只出快照+diff，不写表")
    parser.add_argument(
        "--with-visa", action="store_true", help="附免签口岸数量只读核对"
    )
    args = parser.parse_args(argv)

    from app.services.reservation_seeds import RESERVATION_V0

    settings = _get_settings()
    if settings.llm_backend != "zhipu":
        print(json.dumps({"skipped": "llm_backend != zhipu"}))
        return 0

    # 别名条目（note 以「同「」开头的复述行）继承主馆核对结果，不重复烧 LLM
    primaries = {
        n: p for n, p in RESERVATION_V0.items() if not p["note"].startswith("同「")
    }
    results: dict[str, dict] = {}
    diffs: list[str] = []
    errors = 0
    db_hits = 0
    for i, (name, seed) in enumerate(primaries.items()):
        if i >= args.limit:
            break
        days = seed["days"]
        try:
            rule, usage = _check_one(
                settings, name, "", settings.glm_timeout_seconds + 30
            )
        except Exception as exc:  # 单馆失败不拖垮整批
            errors += 1
            results[name] = {"error": str(exc)[:120]}
            continue
        if rule is None:
            errors += 1
            results[name] = {"error": "non-JSON reply"}
            continue
        bad = _gates(rule)
        if bad:
            errors += 1
            results[name] = {"rejected": bad}
            continue
        results[name] = rule
        if days != rule["advance_days"]:
            diffs.append(f"{name}: 提前天数 {days} → {rule['advance_days']}")
        if not args.dry_run and _apply_db(_session_factory(), name, rule):
            db_hits += 1
    # 别名进快照（标注 inherited，不参与 diff/写表——主馆行已覆盖）
    for alias, seed in RESERVATION_V0.items():
        if not seed["note"].startswith("同「"):
            continue
        for primary in primaries:
            if (
                primary in seed["note"]
                and primary in results
                and "advance_days" in results[primary]
            ):
                results[alias] = dict(results[primary], inherited_from=primary)
                break

    snapshot = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
        "diffs": diffs,
        "db_rows_updated": db_hits,
        "errors": errors,
    }
    _DESIGN.mkdir(exist_ok=True)
    out = _DESIGN / f"reservation_rules_snapshot_{datetime.now():%Y-%m-%d}.json"
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")

    summary = {
        "venues": len(results),
        "diffs": diffs,
        "db_rows_updated": db_hits,
        "errors": errors,
        "snapshot": str(out),
    }
    if args.with_visa:
        summary["visa"] = _visa_report(settings)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
