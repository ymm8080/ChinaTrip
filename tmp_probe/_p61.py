# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\itineraries.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''    # 2026-11-14 用户拍板（ISSUE1）：删行程 = 名下心愿单一并删除——
    # 不再把已排期项退回心愿单（booked 真实订单只解绑、不删）。
    trip_items.purge_itinerary(itinerary_id, actor=device)
''', '''    # 2026-11-14 二拍（覆盖同日「一并删除」口径）：删行程 = 名下心愿行
    # TRIP ID 清空退回心愿单——排期项回心愿单栏，草稿转正，booked 只解绑。
    trip_items.release_itinerary(itinerary_id, actor=device)
''')
sub('''    2026-11-14 用户拍板（覆盖 2026-10-31「退回心愿单」口径）：心愿单随
    行程走——删行程时名下心愿行一并软删留档（DELETION FLAG + 时间/人），
    看板不再出现；booked 是真实订单，只摘行程绑定、订单栏保留。
''', '''    2026-11-14 二拍（覆盖同日「一并删除」口径，回到 2026-10-31 的释放
    语义并补全）：删行程时名下心愿行不删——TRIP ID 清空退回心愿单
    （排期项回心愿单栏、草稿转正、booked 只摘绑定），行保留在心愿单里
    等下一次规划再认领。
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("api ok")
