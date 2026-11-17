# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''                    if target is None and item.poi_id and _name_dup(name, item.name):
                        target = item
''', '''                    # 名字命中即可（占位卡同名概率极低；无 poi_id 的用户
                    # 点名条目也要能对上）
                    if target is None and _name_dup(name, item.name):
                        target = item
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("materialize match relaxed")

p2 = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_wish_draft_lifecycle.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()
old2 = '''            name="豫园",
            city="上海",
            day=1,
            start_time=time(11, 0),'''
new2 = '''            name="豫园",
            poi_id="B-YUYUAN",
            city="上海",
            day=1,
            start_time=time(11, 0),'''
assert t2.count(old2) == 1
t2 = t2.replace(old2, new2, 1)
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("test poi ok")
