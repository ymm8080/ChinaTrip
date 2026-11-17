# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# _sync_planned_rows 的核名：从松散的 _name_dup 收紧为「同一愿望名」
sub('''                for r in rows
                if (item.poi_id and str(r.get("poi_id") or "") == item.poi_id)
                or _name_dup(str(r.get("name") or ""), item.name)
''', '''                for r in rows
                if (item.poi_id and str(r.get("poi_id") or "") == item.poi_id)
                # 2026-11-15：用户原话心愿（「看变脸表演」）不能因为包含关系被
                # 吸附到模型解析出的具名落点（「川剧变脸表演（蜀风雅韵）」）上
                # 翻成已排期——核名只认同一愿望名（归一后等值）。
                or _same_wish_name(str(r.get("name") or ""), item.name)
''')
# materialize 的目标点匹配同口径
sub('''                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上）
                    if target is None and _name_dup(name, item.name):
''', '''                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上），
                    # 但只认同一愿望名——包含关系不吸附（2026-11-15）
                    if target is None and _same_wish_name(name, item.name):
''')
# 新增 helper（放在 _wish_key 之后）
anchor = "def _wish_key(name: str) -> str:\n"
assert t.count(anchor) == 1
i = t.index(anchor)
j = t.index("\n\n\n", i) + 3
helper = '''def _same_wish_name(a: str, b: str) -> bool:
    """同一愿望名（2026-11-15）：归一后等值才算命中——「看变脸表演」不等于
    模型解析出的「川剧变脸表演（蜀风雅韵）」，只有真同一站时才吸附。"""
    ka = _wish_key(a or "")
    kb = _wish_key(b or "")
    return bool(ka) and ka == kb


'''
t = t[:j] + helper + t[j:]
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
