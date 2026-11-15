# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()
t = t.replace('挂靠。""\";\n', '挂靠。""\"\n').replace('后再改。""\";\n', '后再改.""\"\n')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
