# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''    # 2026-11-14 心愿草稿标记（未保存行程的行；正式行恒为 None）
    "draft_session_id",
''', '''    # 2026-11-14 心愿草稿标记（未保存行程的行；正式行恒为 None）
    "draft_session_id",
    # 2026-11-14 USER ID 键（登录账号；未登录为 None）
    "owner_account_id",
''')

# new tests appended at end
t = t.rstrip() + NL + NL + NL + '''def test_list_scopes_by_device_or_user_account():
    """2026-11-14 用户拍板「打开行程中心按 USER ID 出内容」：本设备 + 本登录
    账号的行都算「我的」；换设备登录也看得到；别人的行隐藏；无归属历史行
    维持原可见口径。"""
    app = make_app()
    service = app.dependency_overrides[get_trip_item_service]()
    service.create("我的设备行", source="manual", owner_device_id="dev-1")
    service.create(
        "我的账号行", source="manual", owner_device_id="dev-2", owner_account_id="acc-1"
    )
    service.create("别人的行", source="manual", owner_device_id="dev-3", owner_account_id="acc-2")
    service.create("历史无归属行", source="manual")

    with TestClient(
        app,
        headers={"X-Device-ID": "dev-1", "Authorization": "Bearer tok-acc1"},
    ) as client:
        app.dependency_overrides[_account_from_auth] = lambda: "acc-1"
        body = client.get("/api/v1/trip-items").json()
    names = {r["name"] for group in body.values() for r in group}
    assert names == {"我的设备行", "我的账号行", "历史无归属行"}


def test_commit_drafts_stamps_owner_account():
    svc = TripItemService()
    row = svc.create(
        "豫园", source="chat", itinerary_id="t1", draft_session_id="s1"
    )
    assert svc.commit_drafts("t1", "s1", owner_account_id="acc-1") == 1
    committed = svc.get(row["id"])
    assert committed["owner_account_id"] == "acc-1"
    assert committed["draft_session_id"] is None
'''
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("tests ok")
