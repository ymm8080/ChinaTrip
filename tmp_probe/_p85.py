# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

# PlanSession.wish_sources field
def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''    # 自由输入点名的排除项（2026-11-14 北京小众案）：「尽量避开故宫、长城」
    # 里的地点不是必去，是排除项——不进 must_visits，选点池同名候选直接出局。
    avoid_sites: list[str] = Field(default_factory=list)
''', '''    # 自由输入点名的排除项（2026-11-14 北京小众案）：「尽量避开故宫、长城」
    # 里的地点不是必去，是排除项——不进 must_visits，选点池同名候选直接出局。
    avoid_sites: list[str] = Field(default_factory=list)
    # 心愿来源留档（2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」）：
    # 规划期间建的心愿不再落库——名字 → {source, note, city, dropped}，
    # 保存行程时 materialize_wish_rows 按它物化成正式行。
    wish_sources: dict[str, dict] = Field(default_factory=dict)
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("field ok")
