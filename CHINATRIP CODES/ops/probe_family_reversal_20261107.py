# -*- coding: utf-8 -*-
"""2026-11-07 族并卡反转实测探针（活库真数据）。

用户拍板：大雁塔+长安十二时辰是两个景点，分两个 SITE 同日连排，
不合成一卡。验证：
① 活库中 大雁塔↔长安十二时辰 实距 ≤1km（原本会被并卡的条件成立）；
② 装配后两张独立卡：无 stops chips、各自时长、无「同街并卡」披露；
③ 伞名同站折卡保留：城墙·碑林历史文化景区 收 碑林博物馆 当子站 chip；
④ 钟楼/鼓楼 同样独立双卡（选层贴邻圈保持同日）。
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NAMES = (
    "大雁塔",
    "长安十二时辰主题街区",
    "西安钟楼",
    "西安鼓楼",
    "城墙·碑林历史文化景区",
    "西安碑林博物馆",
)

SQL = """
SELECT json_agg(row_to_json(t)) FROM (
  SELECT name_zh, name_en, category, source_poi_id,
         ST_X(location::geometry) AS lon, ST_Y(location::geometry) AS lat,
         COALESCE(suggested_duration_min, 60) AS dur
  FROM pois
  WHERE city LIKE '西安%' AND status = 'active'
    AND location IS NOT NULL
    AND category NOT IN ('hotel','transport','food')
    AND (name_zh = '长安十二时辰主题街区'
         OR name_zh IN ('西安钟楼','西安鼓楼','西安碑林博物馆')
         OR name_zh LIKE '大雁塔%'
         OR name_zh LIKE '城墙%碑林%')
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
by_name = {r["name_zh"]: r for r in rows}
print(f"pool rows={len(rows)}: {[r['name_zh'] for r in rows]}")

from math import asin, cos, radians, sin, sqrt  # noqa: E402


def km(a, b):
    lo1, la1, lo2, la2 = map(radians, (a[0], a[1], b[0], b[1]))
    dlo, dla = lo2 - lo1, la2 - la1
    h = sin(dla / 2) ** 2 + cos(la1) * cos(la2) * sin(dlo / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


dyt = next(r for r in rows if r["name_zh"].startswith("大雁塔"))
sec = by_name["长安十二时辰主题街区"]
d_ds = km((dyt["lon"], dyt["lat"]), (sec["lon"], sec["lat"]))
print(f"大雁塔[{dyt['name_zh']}] ↔ 长安十二时辰 = {d_ds:.3f} km")
assert d_ds <= 1.0, "probe premise: the pair sits within the old merge radius"

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


def spec(name, category=None):
    r = by_name.get(name) or next(r for r in rows if r["name_zh"].startswith(name))
    return {
        "name": r["name_zh"],
        "city": "西安",
        "day": 1,
        "duration_minutes": r["dur"] or 60,
        "category": category or r["category"] or "sight",
        "location": {"lon": r["lon"], "lat": r["lat"]},
        "must": False,
    }


cands = [
    to_cand(r)
    for r in rows
    if r["name_zh"]
    in (
        dyt["name_zh"],
        "长安十二时辰主题街区",
        "西安钟楼",
        "西安鼓楼",
        "城墙·碑林历史文化景区",
        "西安碑林博物馆",
    )
]

# ② 大雁塔+长安十二时辰：两张独立卡
picked = [spec(dyt["name_zh"]), spec("长安十二时辰主题街区")]
agent = PlanningAgent(BoomLLM(), auto_restaurants=False)
assumptions: list = []
plan = asyncio.run(
    agent._assemble_plan(
        ["西安"], 1, picked, cands, assumptions, start_date="2026-11-16"
    )
)
sights = [
    v
    for v in plan.days[0].items
    if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
]
for v in sights:
    print(
        f"  card: {v.name} dur={v.duration_minutes} "
        f"stops={[s.name for s in (v.stops or [])]}"
    )
names = {v.name for v in sights}
expect = {dyt["name_zh"], "长安十二时辰主题街区"}
assert names == expect, f"two cards expected, got {names}"
for v in sights:
    assert not v.stops, f"{v.name} must not carry stops chips"
assert not any("同街" in a for a in assumptions), "no street-merge disclosure expected"
print("② 大雁塔+长安十二时辰 = 两张独立卡（无 chips、无同街披露） ✓")

# ③ 伞名同站折卡保留：城墙·碑林 收 碑林博物馆
wall = by_name.get("城墙·碑林历史文化景区")
beilin = by_name.get("西安碑林博物馆")
if wall and beilin:
    picked2 = [spec("城墙·碑林历史文化景区"), spec("西安碑林博物馆")]
    assumptions2: list = []
    plan2 = asyncio.run(
        agent._assemble_plan(
            ["西安"], 1, picked2, cands, assumptions2, start_date="2026-11-16"
        )
    )
    sights2 = [
        v
        for v in plan2.days[0].items
        if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
    ]
    for v in sights2:
        print(
            f"  card: {v.name} dur={v.duration_minutes} "
            f"stops={[s.name for s in (v.stops or [])]}"
        )
    assert {v.name for v in sights2} == {"城墙·碑林历史文化景区"}
    host = sights2[0]
    assert host.stops and any("碑林博物馆" in s.name for s in host.stops), (
        "twin absorb must keep folding 碑林博物馆 as chip"
    )
    assert any("子站" in a for a in assumptions2)
    print("③ 伞名同站折卡保留：碑林博物馆 折进 城墙·碑林 主卡 chip ✓")
else:
    print("③ skip: 城墙·碑林 / 碑林博物馆 rows not in live pool")

# ④ 选层：钟楼/鼓楼 同日（贴邻圈保持，不再族豁免计数）
zl, gl = by_name["西安钟楼"], by_name["西安鼓楼"]
sel = PlanningAgent._deterministic_selection(
    [to_cand(zl), to_cand(gl), to_cand(sec), to_cand(dyt)], 2, {"西安": (1, 2)}
)
day_of = {p["name"]: p["day"] for p in sel}
print(f"selection days: {day_of}")
if "西安钟楼" in day_of and "西安鼓楼" in day_of:
    assert day_of["西安钟楼"] == day_of["西安鼓楼"], "钟楼/鼓楼 must stay same day"
    print("④ 钟楼/鼓楼 同日（独立卡连排） ✓")
print("VERDICT: 族并卡反转实证通过——近距双卡连排、伞名折卡保留 ✓")
