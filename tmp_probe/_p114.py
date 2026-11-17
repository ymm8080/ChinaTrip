# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:80])
    t = t.replace(old, new)

# InvalidSourceError 是 ValueError 子类，不必单独列出（未导入会 F821）
sub("            except (InvalidSourceError, ValueError):\n", "            except ValueError:\n", 2)
# E703 多余分号（docstring 尾部）
sub('        物化成行时一并落库。保留入口只为兼容既有调用。""";\n', '        物化成行时一并落库。保留入口只为兼容既有调用。"""\n')
# E501 行宽
sub('''            off_trip = bool(
                city and trip_cities and _norm_city(city).removesuffix("市") not in trip_cities
            )
''', '''            off_trip = bool(
                city
                and trip_cities
                and _norm_city(city).removesuffix("市") not in trip_cities
            )
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("fix ok")
