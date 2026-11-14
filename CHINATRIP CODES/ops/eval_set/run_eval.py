"""固定评测集运行器（P6 评测基建）。

逐条 query 走真实规划入口 ``PlanningAgent.start``（进程内直调，不起
HTTP 服务），收集可量化结果：validate_plan 通过与否/硬闸驳回数、降级
披露条数、占位卡数量、LLM 介入次数、期望约束命中情况。

确定性口径：
- 选点模式锁 algorithm（``PLAN_SELECT_MODE=algorithm``，默认值即此，
  这里显式钉死防环境变量污染）——v0 生成零 LLM 调用；若某条 query
  的降级链（§6.9 硬校验 miss → LLM self-repair）仍触到 LLM，
  ``GuardLLM`` 记数并抛 ``LLMError``（与 LLM 不可用同路径），结果里
  ``llm_calls`` 即为介入次数。
- 火车/航班用 Mock 服务（确定性；真实 12306/VariFlight 既不可达也
  不可复现）。
- POI 候选读活库 PG（docker chinatripcodes-db-1），与线上一致；
  ``--dry-run`` 跳过 DB，走占位兜底，只做单条冒烟。

可重复：同一库快照 + 同一 queries.jsonl → 同一份结果 JSON。
任何失败（单条 query 异常/DB 断）都留痕：结果里 ``status="error"``
带 traceback，日志落 devlogs/eval_run_<ts>.log，绝不静默吞。

用法：
    python ops/eval_set/run_eval.py                      # 全量，结果打 stdout
    python ops/eval_set/run_eval.py --query xian-3d-rain # 单条
    python ops/eval_set/run_eval.py --dry-run --query sh-2d-museum  # 无 DB 冒烟
    python ops/eval_set/run_eval.py --out results.json   # 落盘
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

# 钉死确定性选点（tests/test_algo_v0.py 同款口径），防环境变量污染。
os.environ["PLAN_SELECT_MODE"] = "algorithm"

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from app.services.agent.plan import (  # noqa: E402
    PLACEHOLDER_POI_LABELS,
    PlanningAgent,
)
from app.services.itinerary import (  # noqa: E402
    ItineraryPlan,
    TransferItem,
    validate_plan,
)
from app.services.itinerary.models import VisitItem  # noqa: E402
from app.services.llm import LLMError  # noqa: E402

logger = logging.getLogger("eval_set.runner")

_QUERIES_PATH = Path(__file__).resolve().parent / "queries.jsonl"
_LOG_DIR = _REPO_ROOT / "devlogs"

# 降级披露口径：plan.assumptions 里含这些词的条目计入降级披露数。
_DEGRADATION_TOKENS = ("占位", "降级", "兜底", "未获取", "无数据", "placeholder")


class GuardLLM:
    """评测护栏：算法模式下 LLM 被调用即记数并按「LLM 不可用」路径失败。

    复刻 tests 里 BoomLLM 的手法，但走 LLMError（agent 降级链能接住）
    而不是 AssertionError（会直接炸穿评测循环）。
    """

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        self.calls += 1
        logger.warning("eval guard: LLM called %d times (degradation path)", self.calls)
        raise LLMError("eval guard: no LLM in deterministic eval mode")


def _setup_logging() -> Path:
    _LOG_DIR.mkdir(exist_ok=True)
    log_path = _LOG_DIR / f"eval_run_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)
    return log_path


def _build_agent(*, use_db: bool) -> PlanningAgent:
    """镜像 app/api/plan.py get_planning_agent 的接线，去掉不可复现源。

    - LLM → GuardLLM（记数+护栏）
    - amap/search_chain → 不用（配额不可复现；候选不足走占位并披露）
    - trains/flights → Mock（确定性）
    - poi_details/ctrip_hours/weather → 活库（use_db=True 时），与线
      上读侧一致
    """
    poi_details = None
    ctrip_hours = None
    weather_lookup = None
    if use_db:
        from app.db import get_session_factory
        from app.services.ctrip_hours import get_ctrip_hours
        from app.services.poi_details import get_poi_detail_store
        from app.services.weather import daily_weather_text

        try:
            factory = get_session_factory()
        except Exception:
            logger.error("eval: DB session factory unavailable", exc_info=True)
            factory = None
        if factory is not None:
            poi_details = get_poi_detail_store()
            ctrip_hours = get_ctrip_hours()
            weather_lookup = partial(daily_weather_text, factory)
    return PlanningAgent(
        GuardLLM(),
        amap_client=None,
        search_chain=None,
        train_service=None,  # None → MockTrainService
        flight_service=None,  # None → MockFlightService
        time_budget_seconds=10.0,
        trip_items=None,
        poi_details=poi_details,
        ctrip_hours=ctrip_hours,
        weather_lookup=weather_lookup,
    )


def _is_placeholder(item: VisitItem) -> bool:
    name = item.name or ""
    return any(name.endswith(label) for label in PLACEHOLDER_POI_LABELS)


def _plan_metrics(plan: ItineraryPlan, llm_calls: int) -> dict:
    report = validate_plan(plan, poi_hours=[])
    errors = [v for v in report.violations if v.severity.value == "error"]
    warnings = [v for v in report.violations if v.severity.value == "warning"]
    visits = [i for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    transfers = [i for d in plan.days for i in d.items if isinstance(i, TransferItem)]
    placeholders = [i for i in visits if _is_placeholder(i)]
    assumptions = list(plan.assumptions)
    degradations = [
        a for a in assumptions if any(t in a.lower() for t in _DEGRADATION_TOKENS)
    ]
    return {
        "validate_ok": report.ok,
        "hard_violations": len(errors),
        "warning_violations": len(warnings),
        "violations_by_rule": {
            str(v.rule_id): sum(1 for x in report.violations if x.rule_id == v.rule_id)
            for v in report.violations
        },
        "visit_items": len(visits),
        "transfer_items": len(transfers),
        "placeholder_items": len(placeholders),
        "placeholder_names": sorted({i.name for i in placeholders}),
        "assumptions_total": len(assumptions),
        "degradation_disclosures": len(degradations),
        "llm_calls": llm_calls,
    }


def _check_expected(session, expected: dict) -> dict:
    plan = session.plan
    plan_cities = plan.cities if plan is not None else []
    must_visits = expected.get("must_visits") or []
    plan_names: set[str] = set()
    if plan is not None:
        for d in plan.days:
            for i in d.items:
                if isinstance(i, VisitItem):
                    plan_names.add(i.name)
    return {
        "cities_match": plan_cities == list(expected.get("cities") or []),
        "plan_cities": plan_cities,
        "days_match": (plan is not None and len(plan.days) == expected.get("days")),
        "plan_days": len(plan.days) if plan is not None else 0,
        "must_visits_found": {m: any(m in n for n in plan_names) for m in must_visits},
    }


async def _run_one(agent: PlanningAgent, q: dict) -> dict:
    result: dict = {"id": q["id"], "note": q.get("note", "")}
    calls_before = agent._llm.calls  # 计数器是 agent 级累计，取每条的增量
    session = await agent.start(
        device_id="eval",
        cities=list(q.get("cities") or []),
        days=int(q.get("days") or 0),
        preferences=q.get("preferences") or "",
        city_days=q.get("city_days"),
        start_date=q.get("start_date"),
        intercity_mode=q.get("intercity_mode") or "auto",
        lang=q.get("lang"),
    )
    result["state"] = session.state
    result["clarify_count"] = session.clarify_count
    if session.plan is None:
        result["status"] = "no_plan"
        result["llm_calls"] = agent._llm.calls - calls_before
        result["assumptions"] = list(session.assumptions)
        return result
    result["status"] = "ok"
    result.update(_plan_metrics(session.plan, agent._llm.calls - calls_before))
    result["checks"] = _check_expected(session, q.get("expected") or {})
    result["assumptions"] = list(session.plan.assumptions)
    return result


def _load_queries(path: Path) -> list[dict]:
    queries = []
    with io.open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                queries.append(json.loads(line))
            except json.JSONDecodeError:
                raise SystemExit(f"queries.jsonl 第 {lineno} 行不是合法 JSON")
    return queries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--query", help="只跑指定 id 的单条 query")
    parser.add_argument("--dry-run", action="store_true", help="不连 DB，占位兜底冒烟")
    parser.add_argument("--out", help="结果 JSON 落盘路径（缺省打 stdout）")
    parser.add_argument(
        "--queries", default=str(_QUERIES_PATH), help="自定义 queries.jsonl"
    )
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    log_path = _setup_logging()
    queries = _load_queries(Path(args.queries))
    if args.query:
        queries = [q for q in queries if q["id"] == args.query]
        if not queries:
            print(f"未找到 query: {args.query}", file=sys.stderr)
            return 2

    agent = _build_agent(use_db=not args.dry_run)
    results = []
    for q in queries:
        logger.info("eval run query %s (%s)", q["id"], q.get("note", ""))
        try:
            results.append(asyncio.run(_run_one(agent, q)))
        except Exception:  # noqa: BLE001 —— 单条失败留痕不吞，继续下一条
            logger.error("eval query %s crashed", q["id"], exc_info=True)
            results.append(
                {
                    "id": q["id"],
                    "status": "error",
                    "traceback": traceback.format_exc(),
                }
            )

    summary = {
        "meta": {
            "mode": "dry-run" if args.dry_run else "live-library",
            "select_mode": os.environ.get("PLAN_SELECT_MODE"),
            "log": str(log_path),
            "ran_at": datetime.now(timezone.utc).isoformat(),
        },
        "totals": {
            "queries": len(results),
            "ok": sum(1 for r in results if r.get("status") == "ok"),
            "no_plan": sum(1 for r in results if r.get("status") == "no_plan"),
            "error": sum(1 for r in results if r.get("status") == "error"),
            "validate_ok": sum(1 for r in results if r.get("validate_ok")),
            "hard_violations": sum(r.get("hard_violations", 0) for r in results),
            "degradation_disclosures": sum(
                r.get("degradation_disclosures", 0) for r in results
            ),
            "placeholder_items": sum(r.get("placeholder_items", 0) for r in results),
            "llm_calls": sum(r.get("llm_calls", 0) for r in results),
        },
        "results": results,
    }
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"结果已写入 {args.out}（日志 {log_path}）")
    else:
        print(payload)
    return 0 if summary["totals"]["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
