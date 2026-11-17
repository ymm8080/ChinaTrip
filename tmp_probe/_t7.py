import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''    return get_plan_sessions().get(sid, device_id=DEVICE_HEADERS["X-Device-ID"])
'''
new = '''    store = client.app.dependency_overrides[get_plan_sessions]()
    return store.get(sid, device_id=DEVICE_HEADERS["X-Device-ID"])
'''
assert t.count(old) == 1
t = t.replace(old, new)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
