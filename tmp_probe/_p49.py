# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_changes.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''def rewrite_trip_detail(session, uid, plan) -> None:
''', '''def rewrite_trip_detail(
    session, uid, plan, *, owner_account_id: str | None = None
) -> None:
''')
sub('''                ItineraryItem(
                    id=uuid.uuid4(),
                    itinerary_id=uid,
''', '''                ItineraryItem(
                    id=uuid.uuid4(),
                    itinerary_id=uid,
                    # 2026-11-14（用户拍板「TRIP ITEM 也要 USER ID 列」）：
                    # 明细行冗余登录账号（从头表带下来）
                    owner_account_id=owner_account_id,
''')
sub('''            rewrite_trip_detail(session, uid, new_plan)
''', '''            rewrite_trip_detail(
                session,
                uid,
                new_plan,
                owner_account_id=getattr(record, "owner_account_id", None),
            )
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("trip_changes ok")

# backfill.py: HandoffRecord + create + persist stamp
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\services\backfill.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()

sub('''    refund_summary: str | None = None
    created_at: datetime
    updated_at: datetime
''', '''    refund_summary: str | None = None
    # 2026-11-14（用户拍板「预订埋点也要 USER ID 列」）：登录账号随行留档
    owner_account_id: str | None = None
    created_at: datetime
    updated_at: datetime
''', 1) if t2.count('''    refund_summary: str | None = None
    created_at: datetime
    updated_at: datetime
''') == 1 else None
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("backfill record ok")
