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

# brief 点选轮：规划期记会话，保存才落库
sub('''    assert data["plan"] is not None
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]
    assert "你确认的" in data["reply"]
''', '''    assert data["plan"] is not None
    # 2026-11-15 拍板：规划期不写行，点选的必去记在会话
    assert svc.list_groups()["wishlist"] == []
    assert "天坛" in agent.sessions.get(sid).wish_sources
    assert "你确认的" in data["reply"]
    r = client.post(
        f"/api/v1/plan/{sid}/save", json={"name": "北京两日"}, headers=DEVICE_HEADERS
    )
    assert r.status_code == 201
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]
''')

# 图片读点轮：同一口径
sub('''    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "ready"
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]
''', '''    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "ready"
    # 2026-11-15 拍板：规划期不写行；保存才物化
    assert svc.list_groups()["wishlist"] == []
    assert "天坛" in agent.sessions.get(sid).wish_sources
    r = client.post(
        f"/api/v1/plan/{sid}/save", json={"name": "北京两日"}, headers=DEVICE_HEADERS
    )
    assert r.status_code == 201
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("patch2 ok")
