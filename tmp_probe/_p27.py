# -*- coding: utf-8 -*-
import io

# 1) pg_state.purge_stale_drafts: physical DELETE -> soft delete (DELETION FLAG)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''        if not self._pg_ok:
            return 0
        try:
            with self._session_factory() as session, session.begin():
                result = session.execute(
                    text(
                        "DELETE FROM trip_items"
                        " WHERE draft_session_id IS NOT NULL"
                        "   AND created_at < NOW() - (:days || \' days\')::interval"
                    ),
                    {"days": days},
                )
'''
new = '''        if not self._pg_ok:
            return 0
        # 2026-11-14 用户拍板「心愿单被删也要在数据库里留档/打删除标记」：
        # 过期草稿不物理删——打 DELETION FLAG + 日期/时间/人（wish_items
        # 视图本就整列透出，审计可查），读口（_pg_reload_items/看板）不再返回。
        now = datetime.now(timezone.utc)
        try:
            with self._session_factory() as session, session.begin():
                result = session.execute(
                    text(
                        "UPDATE trip_items"
                        " SET deletion_flag = TRUE,"
                        "     deletion_date = :ddate,"
                        "     deletion_time = :dtime,"
                        "     deleted_by = \'draft-expired\',"
                        "     payload = COALESCE(payload, \'{}\'::jsonb)"
                        "       || jsonb_build_object("
                        "            \'deletion_flag\', TRUE,"
                        "            \'deletion_date\', :ddate_iso,"
                        "            \'deletion_time\', :dtime,"
                        "            \'deleted_by\', \'draft-expired\')"
                        " WHERE draft_session_id IS NOT NULL AND deletion_flag = FALSE"
                        "   AND created_at < NOW() - (:days || \' days\')::interval"
                    ),
                    {
                        "days": days,
                        "ddate": now.date(),
                        "dtime": now.strftime("%H:%M:%S"),
                        "ddate_iso": now.date().isoformat(),
                    },
                )
'''
assert t.count(old) == 1, t.count(old)
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("pg_state soft-delete ok")

# 2) api/trip_items list: no-store
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\api\trip_items.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()
old2 = '''async def list_trip_items(
    itinerary_id: str | None = None,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    store: ItineraryStore = Depends(get_store),
) -> dict:
'''
new2 = '''async def list_trip_items(
    itinerary_id: str | None = None,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: TripItemService = Depends(get_trip_item_service),
    store: ItineraryStore = Depends(get_store),
    response: Response = None,
) -> dict:
'''
assert t2.count(old2) == 1, t2.count(old2)
t2 = t2.replace(old2, new2, 1)
old2b = '''    body = service.list_groups(
        itinerary_id or None, x_device_id or None, include_drafts=False
    )
'''
new2b = '''    # 2026-11-14（用户拍板「行程中心显示数据库信息，不吃缓存」）：看板
    # 读口永不缓存——浏览器/SW 任何一层缓存都会让删掉的心愿闪回。
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
    body = service.list_groups(
        itinerary_id or None, x_device_id or None, include_drafts=False
    )
'''
assert t2.count(old2b) == 1
t2 = t2.replace(old2b, new2b, 1)
# ensure Response import
if "from fastapi import" in t2 and "Response" not in t2.split("from fastapi import",1)[1].split("\n",2)[1]:
    pass
import re
m = re.search(r"from fastapi import ([^\n]+)\n", t2)
print("fastapi import line:", m.group(0).strip() if m else None)
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("api no-store ok")
