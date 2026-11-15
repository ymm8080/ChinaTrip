# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_wish_draft_lifecycle.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = NL.join([
'    session = _session(wish_sources={"豫园": {"source": "chat", "note": "来自聊天", "city": "上海"}})',
'    session.must_visits = ["豫园"]',
'    session.avoid_sites = ["迪士尼"]',
'',
'    agent.commit_wish_drafts(session, account="acc-1")',
])
new = NL.join([
'    session = _session(wish_sources={"豫园": {"source": "chat", "note": "来自聊天", "city": "上海"}})',
'    session.must_visits = ["豫园"]',
'    session.avoid_sites = ["迪士尼"]',
'    # 排期里有豫园（外滩之后）：物化时应翻已排期',
'    session.plan.days[0].items.append(',
'        VisitItem(',
'            item_id="v2",',
'            name="豫园",',
'            city="上海",',
'            day=1,',
'            start_time=time(11, 0),',
'            end_time=time(12, 30),',
'            duration_minutes=90,',
'            location=GeoPoint(lon=121.49, lat=31.23),',
'        )',
'    )',
'',
'    agent.commit_wish_drafts(session, account="acc-1")',
])
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("test fixed")
