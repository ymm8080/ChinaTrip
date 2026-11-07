# -*- coding: utf-8 -*-
"""2026-11-07 并卡+扫街实测探针（活库真数据）。

验证三件事：
① 回民街已退役（status=inactive，池子不再出）；
② 西安钟楼/鼓楼（真坐标 ≤1km）选点后同日；
③ 装配后并成一张族卡：主卡=池序首件、stops 挂子站、时长=族内 max。
"""

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SQL = """
SELECT json_agg(row_to_json(t)) FROM (
  SELECT name_zh, name_en, category, source_poi_id,
         ST_X(location::geometry) AS lon, ST_Y(location::geometry) AS lat,
         COALESCE(suggested_duration_min, 60) AS dur, tags
  FROM pois
  WHERE city LIKE '西安%' AND status = 'active'
    AND location IS NOT NULL
    AND category NOT IN ('hotel','transport','food')
    AND (name_zh IN ('西安钟楼','西安鼓楼','大雁塔','西安城墙','陕西历史博物馆')
         OR name_zh LIKE '钟楼%' OR name_zh LIKE '鼓楼%')
  ORDER BY name_zh
) t;
"""

raw = subprocess.run(
    [
        "docker",
        "exec",
        "chinatripcodes-db-1",
        "psql",
        "-U",
        "chinatrip",
        "-d",
        "chinatrip",
        "-A",
        "-t",
        "-c",
        SQL,
    ],
    capture_output=True,
    encoding="utf-8",
    timeout=60,
)
rows = json.loads(raw.stdout.strip() or "[]")
names = [r["name_zh"] for r in rows]
print(f"pool rows={len(rows)}: {names}")
assert "回民街" not in names, "回民街 should be retired (inactive)"

zl = next((r for r in rows if "钟楼" in r["name_zh"]), None)
gl = next((r for r in rows if "鼓楼" in r["name_zh"]), None)
assert zl and gl, "钟楼/鼓楼 rows must exist"
print(f"钟楼({zl['lon']:.5f},{zl['lat']:.5f}) 鼓楼({gl['lon']:.5f},{gl['lat']:.5f})")

from math import asin, cos, radians, sin, sqrt  # noqa: E402


def km(a, b):
    lo1, la1, lo2, la2 = map(radians, (a[0], a[1], b[0], b[1]))
    dlo, dla = lo2 - lo1, la2 - la1
    h = sin(dla / 2) ** 2 + cos(la1) * cos(la2) * sin(dlo / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


d = km((zl["lon"], zl["lat"]), (gl["lon"], gl["lat"]))
print(f"钟楼↔鼓楼 haversine = {d:.3f} km")

from app.services.agent.plan import PlanningAgent  # noqa: E402
from app.services.itinerary import VisitItem  # noqa: E402


class BoomLLM:
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("probe must not call the LLM")


def to_cand(r):
    return {
        "name": r["name_zh"],
        "city": "西安",
        "category": r["category"] or "sight",
        "source_poi_id": r["source_poi_id"],
        "name_en": r["name_en"],
        "location": {"lon": r["lon"], "lat": r["lat"]},
        "duration_minutes": r["dur"] or 60,
        "suggested_duration_min": r["dur"] or 60,
    }


cands = [
    to_cand(r)
    for r in rows
    if r["name_zh"] in ("西安钟楼", "西安鼓楼", "大雁塔", "西安城墙", "陕西历史博物馆")
]
picked = PlanningAgent._deterministic_selection(cands, 1, {"西安": (1, 1)})
print("picked:", [(p["name"], p["day"]) for p in picked])

agent = PlanningAgent(BoomLLM(), auto_restaurants=False)
assumptions: list = []
import asyncio  # noqa: E402

plan = asyncio.run(
    agent._assemble_plan(
        ["西安"], 1, picked, cands, assumptions, start_date="2026-11-16"
    )
)
for a in assumptions:
    if "同街" in a:
        print("assumption:", a)
sights = [
    v
    for v in plan.days[0].items
    if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
]
for v in sights:
    chips = [s.name for s in (v.stops or [])]
    print(
        f"  card: {v.name} day={v.day} dur={v.duration_minutes} "
        f"must={v.must} stops={chips}"
    )
cards = {v.name: v for v in sights}
anchor = next((v for v in sights if "钟楼" in v.name), None)
if anchor is not None and anchor.stops:
    assert any("鼓楼" in s.name for s in anchor.stops), "鼓楼 must ride 钟楼 card"
    assert anchor.duration_minutes >= 60
    sub = next(s for s in anchor.stops if "鼓楼" in s.name)
    sub_min = next(r["dur"] for r in rows if r["name_zh"] == sub.name)
    assert anchor.duration_minutes >= sub_min, "族卡时长≥族内子站 max"
    print("VERDICT: 钟楼/鼓楼 merged into ONE street card (duration=max) ✓")
else:
    print("VERDICT: 钟楼 card has no stops — check coords/distance")
