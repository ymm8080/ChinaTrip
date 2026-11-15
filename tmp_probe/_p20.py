# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''            floor = (
                arrival_floor_minutes(last)
                if last.mode in ("train", "flight")
                else INTERCITY_BUFFER_MINUTES
            )
'''
new = '''            floor = (
                # 2026-11-14 修并行 WIP 笔误：arrival_floor_minutes 吃的是
                # mode 字符串，传整个 TransferItem 会让 plan/start 全 500
                arrival_floor_minutes(last.mode)
                if last.mode in ("train", "flight")
                else INTERCITY_BUFFER_MINUTES
            )
'''
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
