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

sub('''        if session.source_itinerary_id or session.wish_committed:
            return None
        return session.session_id
''', '''        # 2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」：规划期间
        # 不再建草稿行（愿望走会话 wish_sources，保存物化）——恒 None。
        return None
''')
sub('''        committed = self.materialize_wish_rows(session, account=account)
        self.sync_trip_rows(session, at_save=True)
        session.wish_committed = True
        session.wish_drafts = {}
''', '''        committed = self.materialize_wish_rows(session, account=account)
        self.sync_trip_rows(session, at_save=True)
        session.wish_committed = True
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
