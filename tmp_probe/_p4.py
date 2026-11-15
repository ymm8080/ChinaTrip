# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\trip_items.py"
text = io.open(p, encoding="utf-8", newline="").read()
orig = text

def sub(old, new, n=1):
    global text
    c = text.count(old)
    assert c == n, (c, old[:90])
    text = text.replace(old, new)

sub('''    # 2026-11-13（用户拍板「看板就是数据库的数据」）：按设备读自己的行\r
    body = service.list_groups(itinerary_id or None, x_device_id or None)\r
''', '''    # 2026-11-13（用户拍板「看板就是数据库的数据」）：按设备读自己的行。\r
    # 2026-11-14（用户拍板「没保存行程，心愿单不该保存」）：会话草稿行\r
    # 只在规划引擎内部可见——看板一律不返回，保存行程后才出现。\r
    body = service.list_groups(\r
        itinerary_id or None, x_device_id or None, include_drafts=False\r
    )\r
''')

sub('''    item = service.get(item_id)\r
    if item is None:\r
        raise HTTPException(status_code=404, detail="not_found")\r
    return item\r
''', '''    item = service.get(item_id)\r
    if item is None or item.get("draft_session_id"):\r
        # 草稿行（未保存行程）对外不存在——与看板读口同口径\r
        raise HTTPException(status_code=404, detail="not_found")\r
    return item\r
''')

io.open(p, "w", encoding="utf-8", newline="").write(text)
print("trip_items api patched", len(orig), "->", len(text))

p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\api\itineraries.py"
text = io.open(p2, encoding="utf-8", newline="").read()
orig2 = text
sub('''    device = _require_device(x_device_id)\r
    _owned_record(store, itinerary_id, device, account)\r
    trip_items.release_itinerary(itinerary_id, actor=device)\r
''', '''    device = _require_device(x_device_id)\r
    _owned_record(store, itinerary_id, device, account)\r
    # 2026-11-14 用户拍板（ISSUE1）：删行程 = 名下心愿单一并删除——\r
    # 不再把已排期项退回心愿单（booked 真实订单只解绑、不删）。\r
    trip_items.purge_itinerary(itinerary_id, actor=device)\r
''')
sub('''    """Delete an owned itinerary together with its snapshots (2026-10-20:\r
    「行程」页 per-trip 查看/删除 buttons). Unknown / foreign-owner ids\r
    answer 404 like every other route (no enumeration). 2026-10-31（用户\r
    拍板）：删行程前名下 scheduled 行先回心愿单栏（day/position/booking_id\r
    清空；booked 保留真实订单不动）——先释放后删除，释放失败行程仍在，\r
    可重试。trip_items 依旧不物理删除：看板自有真相（铁律 0）。"""\r
''', '''    """Delete an owned itinerary together with its snapshots (2026-10-20:\r
    「行程」页 per-trip 查看/删除 buttons). Unknown / foreign-owner ids\r
    answer 404 like every other route (no enumeration).\r
\r
    2026-11-14 用户拍板（覆盖 2026-10-31「退回心愿单」口径）：心愿单随\r
    行程走——删行程时名下心愿行一并软删留档（DELETION FLAG + 时间/人），\r
    看板不再出现；booked 是真实订单，只摘行程绑定、订单栏保留。"""\r
''')

io.open(p2, "w", encoding="utf-8", newline="").write(text)
print("itineraries api patched", len(orig2), "->", len(text))
