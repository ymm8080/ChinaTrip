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

# imports: need _account_from_auth
if "_account_from_auth" not in t[:2000]:
    sub('''from fastapi import APIRouter, Depends, HTTPException''', '''from fastapi import APIRouter, Depends, Header, HTTPException''', 0) if t.count("from fastapi import APIRouter, Depends, HTTPException") == 1 else None
    import re
    m = re.search(r"from fastapi import ([^\n]+)\n", t)
    line = m.group(0)
    newline = line.rstrip()
    if "Header" not in newline:
        newline = newline[:-1] + ", Header\n"
    if "_account_from_auth" not in newline:
        pass
    t = t.replace(line, newline, 1)
    t = t.replace(newline, newline + "from app.api.itineraries import _account_from_auth\n", 1)

# order_intent: device/account deps + stamp
sub('''async def order_intent(
    request: OrderIntentRequest,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    *,
    tpl_request: Request,
) -> dict:
''', '''async def order_intent(
    request: OrderIntentRequest,
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    *,
    tpl_request: Request,
    account: str | None = Depends(_account_from_auth),
) -> dict:
''')
sub('''        record = get_handoff_store().create(
            action_type="site_ticket",
            channel=_channel_of(intent.authorization_url),
            url=intent.authorization_url,
''', '''        record = get_handoff_store().create(
            action_type="site_ticket",
            channel=_channel_of(intent.authorization_url),
            url=intent.authorization_url,
            # 2026-11-14（用户拍板「预订埋点按 USER ID 落库」）
            owner_account_id=account,
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("booking_auto order_intent ok")
