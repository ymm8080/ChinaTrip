import sys, asyncio, json
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from tests.test_llm_no_questions import v0_reply, edit_reply, _ITEMS
from app.services.agent.plan import PlanningAgent
from app.services.llm.base import ChatResult

class TracedLLM:
    name = "traced"
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        self.calls += 1
        sys0 = messages[0].content[:40].replace("\n", " ")
        print(f"CALL {self.calls}: system={sys0!r} nmsgs={len(messages)}")
        content = self.replies.pop(0) if self.replies else "EXHAUSTED"
        print(f"   -> {content[:80]!r}")
        return ChatResult(content=content, model="traced")

def run(c): return asyncio.run(c)
llm = TracedLLM([
    v0_reply(_ITEMS),
    edit_reply("你想删掉哪一个景点呢？", []),
    edit_reply("已删除", [{"op": "remove", "item_id": "v1"}]),
])
agent = PlanningAgent(llm)
session = run(agent.start(device_id="d1", cities=["上海"], days=1, preferences="博物馆"))
print("--- start done, plan items:", [(i.item_id, i.name) for d in session.plan.days for i in d.items] if session.plan else None)
session, reply, change = run(agent.message(session, "删掉外滩"))
print("calls:", llm.calls)
print("reply:", repr(reply))
print("change:", repr(change))
