# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''def _session(client: TestClient, agent: PlanningAgent, sid: str):
    """取会话本体（看规划期只写会话态、没写库）。"""
    return app_module.get_plan_sessions().get(sid, device_id=DEVICE)
'''
new = '''def _session(client: TestClient, agent: PlanningAgent, sid: str):
    """取会话本体（看规划期只写会话态、没写库）。"""
    return get_plan_sessions().get(sid, device_id=DEVICE)
'''
assert t.count(old.replace(chr(13), "")) == 1
t = t.replace(old.replace(chr(13), ""), new.replace(chr(13), ""))
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
