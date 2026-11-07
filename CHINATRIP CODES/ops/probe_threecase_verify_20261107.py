# -*- coding: utf-8 -*-
"""三案收口实测探针（2026-11-07）：并卡可见 + 夜档时段 + 看熊猫宽恕。

① 别名通道：search_keyword(西安,[熊猫]) 命中 秦岭四宝科学公园（别名
   西安熊猫馆——2026-11-07 curated 入库行）；
② 心愿宽恕：毒行 看熊猫 city=成都 → _wish_city_in_session 按本程
   城市序 [上海,西安,重庆] 宽恕重绑 西安（秦岭四宝经别名够得着）；
③ 全链吸收：StubItems 挂毒行 → _absorb_wishlist → absorbed 含看熊猫、
   披露 note 一条、must_visits 在册；
④ 族卡时段：大雁塔 × 长安十二时辰（DB 真行 bvt show）→ 并一卡、
   stops 在、卡 bvt=show、_is_theme_block 经子站识别为 True、
   solver 摆位 ≥16:00（十二时辰夜档诉求「下午以后」）。
"""

import asyncio
import json
import subprocess
import sys
from datetime import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SQL = """
SELECT json_agg(row_to_json(t)) FROM (
  SELECT name_zh, name_en, category, source, tags, best_visit_time,
         opening_hours, address, rating,
         ST_X(location::geometry) AS lon, ST_Y(location::geometry) AS lat,
         COALESCE(suggested_duration_min, 0) AS dur
  FROM pois
  WHERE city LIKE '西安%' AND status = 'active' AND location IS NOT NULL
    AND (name_zh ~ '(大雁塔|十二时辰)' OR name_en ~* '(wild goose|twelve hours)')
  ORDER BY name_zh
) t;
"""

raw = subprocess.run(
    ["docker", "exec", "chinatripcodes-db-1", "psql", "-U", "chinatrip",
     "-d", "chinatrip", "-A", "-t", "-c", SQL],
    capture_output=True, encoding="utf-8", timeout=60,
)
rows = json.loads(raw.stdout.strip() or "[]")
print(f"[db] dayanta/theme rows={len(rows)}")

# --- ① 别名通道 -------------------------------------------------------------

from app.services.poi_details import get_poi_detail_store  # noqa: E402

store = get_poi_detail_store()
hits = store.search_keyword("西安", ["熊猫"], limit=20)
names = [h["name"] for h in hits]
four = next((h for h in hits if h["name"] == "秦岭四宝科学公园"), None)
print(f"[①] search_keyword(西安,熊猫) hits={names}")
assert four is not None, "别名通道没接通：西安/熊猫 检索不见秦岭四宝"
assert any(
    "熊猫" in (a or "") for a in (four.get("name_aliases") or [])
), "命中但非别名通道"
print(f"[①] OK 秦岭四宝科学公园 经别名 {four['name_aliases']} 命中，"
      f"loc={four.get('location') is not None} addr={bool(four.get('address'))}")

# --- ②/③ 心愿宽恕 + 全链吸收 --------------------------------------------------

from app.services.agent.plan import PlanningAgent, PlanSession  # noqa: E402
from app.services.itinerary import VisitItem  # noqa: E402
from app.services.itinerary.solver import _is_theme_block  # noqa: E402


class BoomLLM:
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        raise AssertionError("probe must not call the LLM")


class StubItems:
    """毒行形状复刻 trip_items 实测：看熊猫 city=成都 status=scheduled。"""

    def __init__(self) -> None:
        self.updates: list = []

    def list_groups(self):
        return {
            "wishlist": [],
            "scheduled": [
                {
                    "id": "62c06465-b0d8-4df8-9452-10b26244942f",
                    "name": "看熊猫",
                    "city": "成都",
                    "status": "scheduled",
                    "itinerary_id": "old-itin-not-current",
                }
            ],
        }

    def update(self, *a, **k):
        self.updates.append((a, k))


agent = PlanningAgent(BoomLLM(), auto_restaurants=False, poi_details=store)
session = PlanSession(
    session_id="probe-s1", device_id="probe-d1",
    cities=["上海", "西安", "重庆"],
)
forgiven = asyncio.run(agent._wish_city_in_session("看熊猫", session))
print(f"[②] _wish_city_in_session(看熊猫) → {forgiven}")
assert forgiven == "西安", f"宽恕落错城：{forgiven}"

stub = StubItems()
agent2 = PlanningAgent(
    BoomLLM(), auto_restaurants=False, poi_details=store, trip_items=stub
)
session2 = PlanSession(
    session_id="probe-s2", device_id="probe-d1",
    cities=["上海", "西安", "重庆"],
)
absorbed, notes = asyncio.run(agent2._absorb_wishlist(session2))
print(f"[③] absorbed={absorbed}")
print(f"[③] notes={notes}")
print(f"[③] must_visits={session2.must_visits} site_cities={session2.site_cities}")
assert "看熊猫" in absorbed, "毒行没被吸收"
assert "看熊猫" in session2.must_visits
assert session2.site_cities.get("看熊猫") == "西安"
assert len(notes) == 1 and "宽恕" in notes[0] or "改随本程" in notes[0], notes
print("[②③] OK 宽恕重绑+披露+吸收全链通")

# --- ④ 族卡时段（并卡可见 + 夜档下午/晚上） -----------------------------------


def to_cand(r):
    return {
        "name": r["name_zh"],
        "city": "西安",
        "category": r["category"] or "sight",
        "name_en": r["name_en"],
        "tags": r["tags"] or [],
        "location": {"lon": r["lon"], "lat": r["lat"]},
        "duration_minutes": r["dur"] or 60,
        "suggested_duration_min": r["dur"] or 60,
        "best_visit_time": r["best_visit_time"] or "any",
    }


dayanta = next((r for r in rows if "大雁塔" in r["name_zh"]), None)
shier = next((r for r in rows if "十二时辰" in r["name_zh"]), None)
assert dayanta and shier, f"DB 行缺：dayanta={bool(dayanta)} shier={bool(shier)}"
assert (shier["best_visit_time"] or "") == "show", "十二时辰 bvt 非 show"

cands = [to_cand(dayanta), to_cand(shier)]
picked = PlanningAgent._deterministic_selection(cands, 1, {"西安": (1, 1)})
print(f"[④] picked={[(p['name'], p['day']) for p in picked]}")
plan = asyncio.run(
    agent._assemble_plan(
        ["西安"], 1, picked, cands, [], start_date="2026-11-16"
    )
)
sights = [
    v for v in plan.days[0].items
    if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
]
for v in sights:
    print(
        f"[④] card: {v.name} day={v.day} {v.start_time}-{v.end_time} "
        f"dur={v.duration_minutes} bvt={v.best_visit_time} "
        f"stops={[s.name for s in (v.stops or [])]}"
    )
cards_with_stops = [v for v in sights if v.stops]
assert len(cards_with_stops) == 1, f"预期一族卡，实得 {[v.name for v in sights]}"
card = cards_with_stops[0]
stop_names = [s.name for s in card.stops]
assert stop_names == ["长安十二时辰主题街区"], stop_names
assert card.best_visit_time == "show", f"族卡 bvt={card.best_visit_time}"
assert _is_theme_block(card) is True, "族卡没被认成街区型演出块"
assert card.start_time is not None and card.start_time >= time(16, 0), (
    f"夜档街区卡摆进了上午：{card.start_time}"
)
print(
    f"[④] OK 并卡可见（stops={stop_names}）+ bvt=show + theme-block 识别"
    f" + 摆位 {card.start_time}-{card.end_time}（≥16:00 下午/晚场）"
)
print("VERDICT: 三案全过 ✓")
