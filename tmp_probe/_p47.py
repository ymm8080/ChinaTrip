# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''from app.api.itineraries import _account_from_auth, get_store
''', '''from app.api.itineraries import _account_from_auth, get_store
''', 0)

# import check
if "_account_from_auth" not in t.split("def ")[0]:
    sub('''from app.db import get_session_factory
''', '''from app.api.itineraries import _account_from_auth
from app.db import get_session_factory
''', 0)

sub('''async def create_trip_item(
    request: CreateTripItemRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
) -> dict:
''', '''async def create_trip_item(
    request: CreateTripItemRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
''')
sub('''            # 心愿单数据库 CREATED BY（2026-11-13 用户拍板）
            created_by=x_device_id,
''', '''            # 心愿单数据库 CREATED BY（2026-11-13 用户拍板）
            created_by=x_device_id,
            # 2026-11-14（用户拍板「心愿单按 USER ID 出内容」）：登录账号随行
            owner_account_id=account,
''')

sub('''async def list_trip_items(
    itinerary_id: str | None = None,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    store: ItineraryStore = Depends(get_store),
    response: Response = None,
) -> dict:
''', '''async def list_trip_items(
    itinerary_id: str | None = None,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    store: ItineraryStore = Depends(get_store),
    response: Response = None,
    account: str | None = Depends(_account_from_auth),
) -> dict:
''')
sub('''    body = service.list_groups(
        itinerary_id or None, x_device_id or None, include_drafts=False
    )
''', '''    # 2026-11-14（用户拍板「打开行程中心按 USER ID 出内容」）：本设备 +
    # 本登录账号的行都算「我的」；登录后换设备也看得到。
    body = service.list_groups(
        itinerary_id or None,
        x_device_id or None,
        account,
        include_drafts=False,
    )
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("api trip_items ok")
