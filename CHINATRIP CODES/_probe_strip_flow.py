import sys, asyncio, json
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from tests.test_llm_no_questions import ScriptedLLM, v0_reply, edit_reply, _ITEMS
from app.services.agent.plan import PlanningAgent

def run(c): return asyncio.run(c)
llm = ScriptedLLM([
    v0_reply(_ITEMS),
    edit_reply("你想删掉哪一个景点呢？", []),
    edit_reply("已删除", [{"op": "remove", "item_id": "v1"}]),
])
agent = PlanningAgent(llm)
session = run(agent.start(device_id="d1", cities=["上海"], days=1, preferences="博物馆"))
session, reply, change = run(agent.message(session, "删掉外滩"))
print("calls:", llm.calls)
print("reply:", repr(reply))
print("change:", change)
for m in session.history[-4:]:
    print(m.role, repr(m.content[:120]))
