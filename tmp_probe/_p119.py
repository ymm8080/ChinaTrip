# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''                if (item.poi_id and r.get("poi_id") and r["poi_id"] == item.poi_id)
                or _name_dup(str(r.get("name") or ""), item.name)
''', '''                if (item.poi_id and r.get("poi_id") and r["poi_id"] == item.poi_id)
                # 2026-11-15：用户原话心愿（「看变脸表演」）不能因为包含关系被
                # 吸附到模型解析出的具名落点（「川剧变脸表演（蜀风雅韵）」）上
                # 翻成已排期——核名只认同一愿望名（归一后等值）。
                or _same_wish_name(str(r.get("name") or ""), item.name)
''')
sub('''                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上）
                    if target is None and _name_dup(name, item.name):
''', '''                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上），
                    # 但只认同一愿望名——包含关系不吸附（2026-11-15）
                    if target is None and _same_wish_name(name, item.name):
''')
anchor = "def _wish_core(wish: str) -> str:\n"
assert t.count(anchor) == 1, t.count(anchor)
helper = '''def _same_wish_name(a: str, b: str) -> bool:
    """同一愿望名（2026-11-15）：归一后等值才算命中——「看变脸表演」不等于
    模型解析出的「川剧变脸表演（蜀风雅韵）」，只有真同一站时才吸附。"""
    ka = _wish_key(a or "")
    kb = _wish_key(b or "")
    return bool(ka) and ka == kb


'''
t = t.replace(anchor, helper + anchor, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
