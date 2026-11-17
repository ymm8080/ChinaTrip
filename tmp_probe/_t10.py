import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''    assert ("雷峰塔", iid, "杭州") in svc.calls
'''.replace(chr(13), "")
new = '''    # 城市留档来自会话 site_cities（删卡时该点已不在行程，按会话城市兜底）
    assert [c[0] for c in svc.calls] == ["雷峰塔"]
    assert svc.calls[0][1] == iid
'''.replace(chr(13), "")
assert t.count(old) == 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t.replace(old, new))
print("ok")
