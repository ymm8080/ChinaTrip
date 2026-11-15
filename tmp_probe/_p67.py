# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''                        " SET draft_session_id = NULL,"
                        " owner_account_id = COALESCE(t.owner_account_id, :acct),"
                        " itinerary_ref = COALESCE(t.itinerary_ref, :ref),"
''', '''                        " SET draft_session_id = NULL,"
                        " owner_account_id = COALESCE(t.owner_account_id, :acct),"
                        " itinerary_ref = :ref,"
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("pg commit rebind ok")

# payload itinerary_id := :ref (was COALESCE keep old)
old2 = '''                        "   || jsonb_build_object("
                        "        'itinerary_id',"
                        "        COALESCE(t.payload->>'itinerary_id', :ref))"
'''
new2 = '''                        "   || jsonb_build_object("
                        "        'itinerary_id', :ref)"
'''
sub(old2, new2)

# agent.commit_wish_drafts: orphan adoption with plan names
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()

def sub2(old, new, n=1):
    global t2
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t2.count(old)
    assert c == n, (c, old[:100])
    t2 = t2.replace(old, new)

sub2('''        hook = getattr(self._trip_items, "commit_drafts", None)
        committed = (
            hook(
                itinerary_id,
                session.session_id,
                owner_account_id=(account or getattr(session, "account_id", None)),
            )
            if callable(hook)
            else 0
        )
''', '''        hook = getattr(self._trip_items, "commit_drafts", None)
        committed = (
            hook(
                itinerary_id,
                session.session_id,
                owner_account_id=(account or getattr(session, "account_id", None)),
            )
            if callable(hook)
            else 0
        )
        # 2026-11-14 深夜（用户报「保存了行程，心愿不在已排期」）：同一用户
        # 在多次规划/重开时聊出的心愿行挂在死掉的中途行程号上——保存本次
        # 行程时按名字收编：命中的重绑到本行程（对账后进已排期），没命中
        # 的转正为无行程心愿行。
        orphan_hook = getattr(self._trip_items, "commit_orphan_drafts", None)
        if callable(orphan_hook):
            names = {
                item.name
                for day in session.plan.days
                for item in day.items
                if isinstance(item, VisitItem) and item.name
            }
            committed += orphan_hook(
                itinerary_id,
                owner_device_id=session.device_id,
                owner_account_id=(account or getattr(session, "account_id", None)),
                match_names=names,
            )
''')

io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("agent ok")
