# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''                # 2026-11-15：用户原话心愿（「看变脸表演」）不能因为包含关系被
                # 吸附到模型解析出的具名落点（「川剧变脸表演（蜀风雅韵）」）上
                # 翻成已排期——核名只认同一愿望名（归一后等值）。
                or _same_wish_name(str(r.get("name") or ""), item.name)
''', '''                # 保存对账：用户原话心愿（「看熊猫」）按核心词认到正主
                # （成都大熊猫繁育研究基地）——语义核名（_name_dup）
                or _name_dup(str(r.get("name") or ""), item.name)
''')
sub('''                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上），
                    # 但只认同一愿望名——包含关系不吸附（2026-11-15）
                    if target is None and _same_wish_name(name, item.name):
''', '''                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上）
                    if target is None and _name_dup(name, item.name):
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
