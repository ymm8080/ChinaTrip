import sys, asyncio, json
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from app.services.agent.plan import PlanningAgent, PlanSession, _brief_typo_rival_row
from app.services.poi_details import PoiDetailStore
from app.db import get_session_factory
from app.services.llm.base import ChatResult

BRIEF = ("SHANGHAI 2DAY'S TRIP INCLUDING THE BUND, SHANGHAI MUSEUM, "
         "ORITAL TOWER, CURISE, YUGARDEN ZHUJIAZUI")

class ScriptedLLM:
    name = "scripted"
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        sites = [
            {"name": "外滩", "kind": "sight", "city": "上海", "day": 0},
            {"name": "上海博物馆", "kind": "sight", "city": "上海", "day": 0},
            {"name": "东方明珠广播电视塔", "kind": "sight", "city": "上海", "day": 0},
            {"name": "豫园", "kind": "sight", "city": "上海", "day": 0},
            {"name": "上海中心大厦", "kind": "sight", "city": "上海", "day": 0},
            {"name": "朱家角古镇", "kind": "sight", "city": "上海", "day": 0},
            {"name": "陆家嘴", "kind": "sight", "city": "上海", "day": 0},
        ]
        return ChatResult(content=json.dumps({"sites": sites}, ensure_ascii=False), model="scripted")

async def main():
    store = PoiDetailStore(get_session_factory())
    agent = PlanningAgent(ScriptedLLM(), amap_client=None, poi_details=store)
    session = PlanSession(session_id="s-live", device_id="d1", cities=["上海"], days=2,
                          preferences=BRIEF, brief_text=BRIEF)
    added, notes = await agent._mine_brief_sites(session)
    print("added:", added)
    # raw library check
    rows = store.match_text_names("上海", BRIEF)
    print("library:", [(r["name"], r.get("name_en")) for r in rows])
    # direct canonical check for lujiazui
    can = await agent._canonical_brief_site("陆家嘴", "上海", ["上海"])
    print("canonical lujiazui:", can)
    if can and can[3]:
        print("rival?", _brief_typo_rival_row(BRIEF, [r.get("name_en") for r in rows], can[3]))
asyncio.run(main())
