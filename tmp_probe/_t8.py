# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:80])
    t = t.replace(old, new)

# 统一取法：保存后按最终排期分区（排上的进已排期，没排上的进心愿单）
sub('''    assert r.status_code == 201
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["西湖"]
''', '''    assert r.status_code == 201
    board = svc.list_groups()
    names = [i["name"] for zone in board.values() for i in zone]
    assert "西湖" in names
    assert "灵隐寺" not in names and "西溪湿地" not in names
''')
sub('''    assert r.status_code == 201
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]
''', '''    assert r.status_code == 201
    names = [i["name"] for zone in svc.list_groups().values() for i in zone]
    assert "天坛" in names
    assert "颐和园" not in names
''')
sub('''    assert r.status_code == 201
    assert [i["name"] for i in svc.list_groups()["wishlist"]] == ["天坛"]
''', '''    assert r.status_code == 201
    names = [i["name"] for zone in svc.list_groups().values() for i in zone]
    assert "天坛" in names
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
