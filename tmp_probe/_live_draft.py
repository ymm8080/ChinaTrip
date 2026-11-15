# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import text
from app.db import get_session_factory
from app.services.pg_state import PgTripItemService

svc = PgTripItemService(get_session_factory())
dev = "probe-draft-1114"
row = svc.create(
    "草稿验证点", source="manual", owner_device_id=dev, city="上海",
    draft_session_id="sess-probe-draft",
)
print("created draft flag:", row.get("draft_session_id"))
visible = [i["name"] for i in svc.list_groups(None, dev, include_drafts=False)["wishlist"]]
hidden = [i["name"] for i in svc.list_groups(None, dev)["wishlist"]]
print("visible:", visible, "| engine:", hidden)
with get_session_factory()() as s:
    n = s.execute(text("select count(*) from wish_items where wish_name='草稿验证点'")).scalar()
    print("view rows (must be 0):", n)
print("commit:", svc.commit_drafts("it-probe0001", "sess-probe-draft"))
fresh = svc.get(row["id"])
print("after commit flag:", fresh.get("draft_session_id"), "itin:", fresh.get("itinerary_id"))
print("visible after:", [i["name"] for i in svc.list_groups(None, dev, include_drafts=False)["wishlist"]])
with get_session_factory()() as s:
    n = s.execute(text("select count(*) from wish_items where wish_name='草稿验证点'")).scalar()
    print("view rows after commit (must be 1):", n)
print("purge:", [r["name"] for r in svc.purge_itinerary("it-probe0001", actor=dev)])
print("gone:", svc.get(row["id"]))
