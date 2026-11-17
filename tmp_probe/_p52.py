# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\booking_auto.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

# restaurant_intent create call: add owner_account_id (account already in scope at 333)
sub('''        record = get_handoff_store().create(
            action_type="restaurant",
            channel=_channel_of(url),
            url=url,
''', '''        record = get_handoff_store().create(
            action_type="restaurant",
            channel=_channel_of(url),
            url=url,
            # 2026-11-14（用户拍板「预订埋点按 USER ID 落库」）
            owner_account_id=account,
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("restaurant ok")

# api/backfill.py create_handoff: account dep
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\api\backfill.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()

def sub2(old, new, n=1):
    global t2
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t2.count(old)
    assert c == n, (c, old[:100])
    t2 = t2.replace(old, new)

import re
if "_account_from_auth" not in t2[:2000]:
    m = re.search(r"from fastapi import ([^\n]+)\n", t2)
    line = m.group(0)
    nl = line.rstrip()
    if "Depends" not in nl:
        nl = nl[:-1] + ", Depends\n"
    t2 = t2.replace(line, nl, 1)
    t2 = t2.replace(nl, nl + "from app.api.itineraries import _account_from_auth\n", 1)

sub2('''@router.post("/handoffs", status_code=201)
async def create_handoff(
    request: CreateHandoffRequest,
    store: HandoffStore = Depends(get_handoff_store),
) -> HandoffRecord:
    return store.create(
        action_type=request.action_type,
        channel=request.channel,
        url=request.url,
        refund_summary=request.refund_summary,
    )
''', '''@router.post("/handoffs", status_code=201)
async def create_handoff(
    request: CreateHandoffRequest,
    store: HandoffStore = Depends(get_handoff_store),
    account: str | None = Depends(_account_from_auth),
) -> HandoffRecord:
    return store.create(
        action_type=request.action_type,
        channel=request.channel,
        url=request.url,
        refund_summary=request.refund_summary,
        # 2026-11-14（用户拍板「预订埋点按 USER ID 落库」）
        owner_account_id=account,
    )
''')
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("backfill api ok")
