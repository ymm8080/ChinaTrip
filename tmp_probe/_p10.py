# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

old_key = '''    "created_at",
    "updated_at",
'''
new_key = '''    "created_at",
    "updated_at",
    # 2026-11-14 心愿草稿标记（未保存行程的行；正式行恒为 None）
    "draft_session_id",
'''
assert t.count(old_key) == 1
t = t.replace(old_key, new_key, 1)

start_marker = "# --- 行程删除释放心愿（2026-10-31：删行程 → 已排期心愿回心愿单栏） -------------\n"
end_marker = "def test_list_self_heals_scheduled_orphans_on_deleted_itinerary():\n"
i = t.index(start_marker)
j = t.index(end_marker)
block = '''# --- 心愿单随行程走（2026-11-14 用户拍板） -----------------------------------
#
# ISSUE1「删行程时它的相关心愿单没被删除」：删行程 = 名下心愿单一并软删，
# 不再把排期项重建回心愿单；booked 真实订单只摘行程绑定。
# ISSUE2「没保存行程，心愿单就不该保存」：规划会话建的行带 draft_session_id
# 草稿标记，看板/接口不返回；点「保存行程」提交后才可见。

def test_purge_itinerary_deletes_related_wishes_keeps_booked_and_others():
    svc = TripItemService()
    wish = svc.create("灵隐寺", source="chat", itinerary_id="t1", city="杭州")
    svc.update(wish["id"], status="scheduled", day=2, position=3.0)
    parked = svc.create("河坊街", source="chat", itinerary_id="t1")
    booked = svc.create("宋城", source="manual", itinerary_id="t1")
    svc.update(booked["id"], status="scheduled", day=1)
    svc.update(booked["id"], status="booked", booking_id="BK-9")
    other = svc.create("外滩", source="manual", itinerary_id="t2")
    svc.update(other["id"], status="scheduled", day=1)
    stray = svc.create("随手记", source="manual")
    svc.update(stray["id"], status="scheduled", day=1)

    purged = svc.purge_itinerary("t1", actor="dev-1")

    assert {r["name"] for r in purged} == {"灵隐寺", "河坊街"}
    assert svc.get(wish["id"]) is None
    assert svc.get(parked["id"]) is None
    # 不再重建回心愿单（旧 release 语义已废）
    assert svc.list_groups()["wishlist"] == []
    # booked 保留真实订单、只摘行程绑定；别行程与无行程行原样
    assert svc.get(booked["id"])["status"] == "booked"
    assert svc.get(booked["id"])["booking_id"] == "BK-9"
    assert svc.get(booked["id"])["itinerary_id"] is None
    assert svc.get(other["id"])["itinerary_id"] == "t2"
    assert svc.get(other["id"])["status"] == "scheduled"
    assert svc.get(stray["id"])["status"] == "scheduled"


def test_purge_itinerary_without_rows_or_id_is_noop():
    svc = TripItemService()
    assert svc.purge_itinerary("ghost-trip") == []
    assert svc.purge_itinerary("") == []


def test_drafts_hidden_from_board_until_committed():
    """没点「保存行程」→ 心愿行是草稿：看板/单条读口都不返回；转正后可见。"""
    app = make_app()
    service = app.dependency_overrides[get_trip_item_service]()
    draft = service.create(
        "豫园", source="chat", itinerary_id="t1", city="上海", draft_session_id="s1"
    )
    service.update(draft["id"], status="scheduled", day=1)
    with TestClient(app) as client:
        body = client.get("/api/v1/trip-items").json()
        assert body["wishlist"] == [] and body["scheduled"] == []
        assert client.get(f"/api/v1/trip-items/{draft['id']}").status_code == 404

        assert service.commit_drafts("t1", "s1") == 1
        body = client.get("/api/v1/trip-items").json()
        assert [i["name"] for i in body["scheduled"]] == ["豫园"]
        assert body["scheduled"][0]["draft_session_id"] is None
        assert client.get(f"/api/v1/trip-items/{draft['id']}").status_code == 200


def test_commit_drafts_only_touches_session_or_itinerary_rows():
    svc = TripItemService()
    mine = svc.create("豫园", source="chat", itinerary_id="t1", draft_session_id="s1")
    linked = svc.create("外滩", source="chat", itinerary_id="t1", draft_session_id="s9")
    other = svc.create("西湖", source="chat", draft_session_id="s9")

    assert svc.commit_drafts("t1", "s1") == 2
    assert svc.get(mine["id"])["draft_session_id"] is None
    # 已挂本行程的草稿（历史会话/换局遗留）一并转正
    assert svc.get(linked["id"])["draft_session_id"] is None
    # 别的会话、又没挂本行程：不动
    assert svc.get(other["id"])["draft_session_id"] == "s9"


def test_delete_itinerary_purges_related_wishlist_endpoint():
    """行程页 🗑 删除：行程连同快照、关联心愿单一起删除；booked 保留订单；
    没挂行程的心愿行不受牵连。"""
    app, store = make_app_with_store()
    record = ItineraryService(store).create("dev-1", ["杭州"], days_count=2)
    with TestClient(app) as client:
        scheduled_item = create_item(client, itinerary_id=record.itinerary_id, name="s")
        schedule(client, scheduled_item["id"], 1)
        booked_item = create_item(client, itinerary_id=record.itinerary_id, name="b")
        schedule(client, booked_item["id"], 2)
        book(client, booked_item["id"])
        loose = create_item(client, name="loose")  # 不挂行程：自己的心愿

        resp = client.delete(
            f"/api/v1/itineraries/{record.itinerary_id}",
            headers={"X-Device-ID": "dev-1"},
        )
        assert resp.status_code == 204

        body = client.get("/api/v1/trip-items").json()
        assert body["scheduled"] == []
        names = [r["name"] for group in body.values() for r in group]
        assert "s" not in names  # 不再退回心愿单
        assert [r["name"] for r in body["bookings"]] == ["b"]
        assert body["bookings"][0]["itinerary_id"] is None
        assert [r["name"] for r in body["wishlist"]] == ["loose"]
        assert loose["itinerary_id"] is None
        # 行程本身确已删除（清理没有挡住删除）
        assert (
            client.get(
                f"/api/v1/itineraries/{record.itinerary_id}",
                headers={"X-Device-ID": "dev-1"},
            ).status_code
            == 404
        )


'''
t = t[:i] + block + t[j:]
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("tests rewritten")
