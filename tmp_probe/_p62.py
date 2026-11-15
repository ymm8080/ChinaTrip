# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\itineraries.py"
t = io.open(p, encoding="utf-8", newline=None).read()
lines = t.split(NL)
out = []
i = 0
while i < len(lines):
    l = lines[i]
    if l.startswith("    2026-11-14 用户拍板（覆盖 2026-10-31"):
        out.append("    2026-11-14 二拍（覆盖同日「一并删除」口径，回到 2026-10-31 的释放")
        out.append("    语义并补全）：删行程时名下心愿行不删——TRIP ID 清空退回心愿单")
        out.append("    （排期项回心愿单栏、草稿转正、booked 只摘绑定），行保留在心愿单里")
        out.append("    等下一次规划再认领。\"\"\"")
        # skip until the end of the docstring line (the one ending with """)
        while not lines[i].rstrip().endswith('"""'):
            i += 1
        i += 1
        continue
    if l.strip() == "# 2026-11-14 用户拍板（ISSUE1）：删行程 = 名下心愿单一并删除——":
        out.append("    # 2026-11-14 二拍：删行程 = 名下心愿行 TRIP ID 清空退回心愿单——")
        out.append("    # 排期项回心愿单栏、草稿转正，booked 只解绑（不删不重建）。")
        i += 1
        continue
    if l.strip() == "# 不再把已排期项退回心愿单（booked 真实订单只解绑、不删）。":
        i += 1
        continue
    if "trip_items.purge_itinerary(itinerary_id, actor=device)" in l:
        out.append("    trip_items.release_itinerary(itinerary_id, actor=device)")
        i += 1
        continue
    out.append(l)
    i += 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write(NL.join(out))
print("api docstring fixed")
