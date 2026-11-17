# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()
t = t.replace('agent.sessions.get(sid)', '_session(client, agent, sid)')
helper = '''

def _session(client: TestClient, agent: PlanningAgent, sid: str):
    """取会话本体（看规划期只写会话态、没写库）。"""
    return app_module.get_plan_sessions().get(sid, device_id=DEVICE)
'''
anchor = "def message(client: TestClient, session_id: str, text: str, headers=None):\n"
assert t.count(anchor) == 1
t = t.replace(anchor, helper.strip("\n") + "\n\n\n" + anchor, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("helper ok", t.count("_session(client, agent, sid)"))
