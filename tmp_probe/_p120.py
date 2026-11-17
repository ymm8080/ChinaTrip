# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 物化一律挂本次行程（城市不在行程也挂：心愿单区里带城备注，删行程时
# 统一 TRIP ID 清空退回）；city 只决定「是否翻已排期」
sub('''            off_trip = bool(
                city
                and trip_cities
                and _norm_city(city).removesuffix("市") not in trip_cities
            )
            row = None
''', '''            off_trip = bool(
                city
                and trip_cities
                and _norm_city(city).removesuffix("市") not in trip_cities
            )
            row = None
''')
sub('''                    # 保存行程 = 写库时刻：直接落正式行（无草稿）
                    itinerary_id=(None if off_trip else itinerary_id),
''', '''                    # 保存行程 = 写库时刻：直接落正式行（无草稿），并挂本次
                    # 行程（删行程时统一 TRIP ID 清空退回心愿单）
                    itinerary_id=itinerary_id,
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
