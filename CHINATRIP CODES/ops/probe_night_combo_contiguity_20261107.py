# -*- coding: utf-8 -*-
"""只读探针（2026-11-07）：大雁塔+十二时辰 双卡贴排时刻验证——
反转拍板后两卡是否同日首尾相接（大雁塔下午紧接十二时辰 16 点后夜档）。
不改引擎，复用族并卡反转探针的池子装配。"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SQL = """
SELECT json_agg(row_to_json(t)) FROM (
  SELECT name_zh, name_en, category, source_poi_id, best_visit_time,
         ST_X(location::geometry) AS lon, ST_Y(location::geometry) AS lat,
         COALESCE(suggested_duration_min, 60) AS dur
  FROM pois
  WHERE city LIKE '西安%' AND status = 'active' AND location IS NOT NULL
    AND category NOT IN ('hotel','transport','food')
    AND (name_zh = '长安十二时辰主题街区' OR name_zh LIKE '大雁塔%')
  ORDER BY name_zh
) t;
"""
raw = subprocess.run(
    ["docker", "exec", "chinatripcodes-db-1", "psql", "-U", "chinatrip",
     "-d", "chinatrip", "-A", "-t", "-c", SQL],
    capture_output=True, encoding="utf-8", timeout=60,
)
rows = json.loads(raw.stdout.strip() or "[]")
by_name = {r["name_zh"]: r for r in rows}
print(f"pool rows={[r['name_zh'] for r in rows]}")
print(f"bvt: " + ", ".join(f"{r['name_zh']}={r.get('best_visit_time')}" for r in rows))

from app.services.agent.plan import PlanningAgent  # noqa: E402
from app.services.itinerary import VisitItem  # noqa: E402


class BoomLLM:
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("probe must not call the LLM")


def to_cand(r):
    return {
        "name": r["name_zh"], "city": "西安",
        "category": r["category"] or "sight",
        "source_poi_id": r["source_poi_id"], "name_en": r["name_en"],
        "location": {"lon": r["lon"], "lat": r["lat"]},
        "duration_minutes": r["dur"] or 60,
        "suggested_duration_min": r["dur"] or 60,
        "best_visit_time": r.get("best_visit_time"),
    }


def spec(name):
    r = by_name.get(name) or next(
        r for r in rows if r["name_zh"].startswith(name)
    )
    return {
        "name": r["name_zh"], "city": "西安", "day": 1,
        "duration_minutes": r["dur"] or 60,
        "category": r["category"] or "sight",
        "location": {"lon": r["lon"], "lat": r["lat"]}, "must": False,
    }


cands = [to_cand(r) for r in rows]
picked = [spec("大雁塔"), spec("长安十二时辰主题街区")]
agent = PlanningAgent(BoomLLM(), auto_restaurants=False)
assumptions: list = []
plan = asyncio.run(
    agent._assemble_plan(
        ["西安"], 1, picked, cands, assumptions, start_date="2026-11-16"
    )
)
sights = [
    v for v in plan.days[0].items
    if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
]
seq = []
for v in plan.days[0].items:
    if isinstance(v, VisitItem):
        seq.append(
            f"{v.name} {v.start_time}-{v.end_time} bvt={v.best_visit_time}"
        )
print("day1 timeline:")
for s in seq:
    print(f"  {s}")

shier = next(v for v in sights if "十二时辰" in v.name)
dyt = next(v for v in sights if "大雁塔" in v.name)


def _mins(t):
    return None if t is None else t.hour * 60 + t.minute


shier_s = _mins(shier.start_time)
shier_e = _mins(shier.end_time)
dyt_s = _mins(dyt.start_time)
dyt_e = _mins(dyt.end_time)
assert shier_s >= 16 * 60, f"十二时辰未排 16 点后：{shier.start_time}"
gap = shier_s - dyt_e
contiguous = 0 <= gap <= 30 and dyt_s >= 12 * 60
print(f"贴排判定: 大雁塔 {dyt.start_time}-{dyt.end_time} → "
      f"十二时辰 {shier.start_time}-{shier.end_time} 间隔={gap}min "
      f"贴排={contiguous}")
assert contiguous, "两卡没有首尾相接（大雁塔须下午档贴住夜档开场）"
print("VERDICT: 双卡贴排（同日首尾相接+夜档 16 点后） ✓")
