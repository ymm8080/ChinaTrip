# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 1) sites/confirm：规划期不写行（2026-11-15 拍板），点选结果先记会话，保存才物化
sub('''    assert data["plan"] is not None
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["西湖"]
    assert "未点选的 2 个地点没有写入心愿单" in data["reply"]
''', '''    assert data["plan"] is not None
    # 2026-11-15 用户拍板：规划期不写心愿行（不复制/不缓存），点选结果记会话
    assert svc.list_groups()["wishlist"] == []
    session = agent.sessions.get(sid)
    assert "西湖" in session.wish_sources
    assert "灵隐寺" not in session.wish_sources
    assert "西溪湿地" not in session.wish_sources
    assert "未点选的 2 个地点没有写入心愿单" in data["reply"]
    # 保存行程 = 心愿单落库的唯一写时刻
    r = client.post(
        f"/api/v1/plan/{sid}/save", json={"name": "杭州两日"}, headers=DEVICE_HEADERS
    )
    assert r.status_code == 201
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["西湖"]
''')

# 2) brief 开点选轮：同样改为会话态 + 保存物化
sub('''    body = message(client, sid, "我想去杭州玩两天，喜欢西湖和灵隐寺").json() if False else None
''', '''''', 0)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("patch1 ok")
