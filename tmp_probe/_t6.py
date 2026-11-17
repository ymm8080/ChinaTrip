import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_api.py"
t = io.open(p, encoding="utf-8", newline=None).read()
t = t.replace('device_id=DEVICE)', 'device_id=DEVICE_HEADERS["X-Device-ID"])')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
