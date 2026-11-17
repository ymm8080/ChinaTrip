import sys, asyncio, json
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from tests.test_llm_no_questions import edit_reply
from app.services.agent.plan import PlanningAgent, parse_json_content, _strip_llm_questions
content = edit_reply("已删除", [{"op": "remove", "item_id": "v1"}])
print("content:", content)
data = parse_json_content(content)
print("parsed:", data)
print("reply raw:", repr(str(data.get("reply") or "")))
print("reply stripped:", repr(_strip_llm_questions(str(data.get("reply") or ""))))
async def main():
    agent = PlanningAgent.__new__(PlanningAgent)
    try:
        diffs = agent._coerce_diffs(data.get("diffs"), plan=None)
        print("coerced:", diffs)
    except Exception as e:
        print("coerce err:", e)
asyncio.run(main())
