# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 删卡：规划期记会话 avoid_sites（选择闸即时生效），保存时打 EXCLUSION
sub('''    assert data["reply"] == "已删除 雷峰塔，已记入不想去"
    assert svc.calls == [("雷峰塔", iid, "杭州")]
''', '''    assert data["reply"] == "已删除 雷峰塔，已记入不想去"
    # 2026-11-15 拍板：规划期不写库——排除项先记会话，保存时打 EXCLUSION
    assert svc.calls == []
    assert "雷峰塔" in agent.sessions.get(sid).avoid_sites
    r = client.post(
        f"/api/v1/plan/{sid}/save", json={"name": "沪杭两日"}, headers=DEVICE_HEADERS
    )
    assert r.status_code == 201
    assert ("雷峰塔", iid, "杭州") in svc.calls
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("patch3 ok")
