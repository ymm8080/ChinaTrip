# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()
NL = chr(10)
block = NL.join([
'',
'',
'def test_same_wish_shows_once_in_global_board_across_trips():',
'    """2026-11-15 用户报「颐和园在心愿单出现两行」：全局看板按用户出内容，',
'    同一心愿跨行程也只能出一行（已排期优先，其次最早建的行）。"""',
'    svc = TripItemService()',
'    older = svc.create("颐和园", source="chat", itinerary_id="t1", city="北京",',
'                       owner_device_id="dev-1")',
'    newer = svc.create("颐和园", source="plan_delete", itinerary_id="t2",',
'                       city="北京", owner_device_id="dev-1")',
'    svc.update(newer["id"], status="wishlist", exclusion_flag=True)',
'',
'    board = svc.list_groups(None, "dev-1")',
'    names = [r["name"] for zone in board.values() for r in zone]',
'    assert names.count("颐和园") == 1',
'    # 单一心愿在行程视图里仍按行程过滤（各看各的）',
'    assert [r["name"] for r in svc.list_groups("t2", "dev-1")["wishlist"]] == ["颐和园"]',
'    assert [r["name"] for r in svc.list_groups("t1", "dev-1")["wishlist"]] == ["颐和园"]',
'    assert older["id"] != newer["id"]',
'',
'',
'def test_mark_excluded_claims_existing_wish_instead_of_new_row():',
'    """删站点（EXCLUSION）要认领同一个人已有的同名心愿行，而不是再建一行',
'    ——两行并列正是用户看到的重复。"""',
'    svc = TripItemService()',
'    wish = svc.create("颐和园", source="chat", itinerary_id="t1", city="北京",',
'                      owner_device_id="dev-1")',
'    marked = svc.mark_excluded("颐和园", itinerary_id="t2", city="北京")',
'    assert marked["id"] == wish["id"]',
'    assert marked["exclusion_flag"] is True',
'    all_rows = [r for zone in svc.list_groups(None, "dev-1").values() for r in zone]',
'    assert [r["name"] for r in all_rows].count("颐和园") == 1',
'',
])
anchor = "def test_release_itinerary_returns_wishes_with_blank_trip_id():\n"
assert t.count(anchor) == 1
t = t.replace(anchor, block.lstrip("\n") + anchor, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
