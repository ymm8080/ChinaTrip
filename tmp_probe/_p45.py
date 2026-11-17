# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''    session = PlanSession(
        session_id=uuid.uuid4().hex,
        device_id=x_device_id,
'''
print("count:", t.count(old))
