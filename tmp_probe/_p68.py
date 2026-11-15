# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''            stored["draft_session_id"] = None
            if matched:
                stored["itinerary_id"] = itinerary_id
            stored["updated_at"] = _iso_now(None)
''', '''            stored["draft_session_id"] = None
            if matched:
                stored["itinerary_id"] = itinerary_id
            else:
                # 没命中本次行程：TRIP ID 清空，回到无行程心愿行
                stored["itinerary_id"] = None
            stored["updated_at"] = _iso_now(None)
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("service tweak ok")

p2 = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_trip_items.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()
t2 = t2.rstrip() + NL + NL + NL + '''def test_commit_orphan_drafts_adopts_dead_trip_rows_at_save():
    """保存行程时收编同用户挂在死行程上的孤儿草稿：名字命中→重绑到本行程
    （对账后进已排期）；没命中→转正为无行程心愿行（TRIP ID 清空）；
    别人的草稿不动。"""
    svc = TripItemService()
    mine_hit = svc.create(
        "天坛",
        source="chat",
        itinerary_id="dead1",
        owner_device_id="dev-1",
        draft_session_id="sA",
    )
    svc.update(mine_hit["id"], status="scheduled", day=1)
    mine_miss = svc.create(
        "豫园",
        source="chat",
        itinerary_id="dead1",
        owner_device_id="dev-1",
        draft_session_id="sA",
    )
    other = svc.create(
        "故宫",
        source="chat",
        itinerary_id="dead2",
        owner_device_id="dev-2",
        draft_session_id="sB",
    )

    committed = svc.commit_orphan_drafts(
        "t-live",
        owner_device_id="dev-1",
        match_names={"天坛", "颐和园"},
    )

    assert committed == 2
    hit = svc.get(mine_hit["id"])
    assert hit["draft_session_id"] is None
    assert hit["itinerary_id"] == "t-live"
    miss = svc.get(mine_miss["id"])
    assert miss["draft_session_id"] is None
    assert miss["itinerary_id"] is None
    assert miss["status"] == "wishlist"
    assert svc.get(other["id"])["draft_session_id"] == "sB"  # 别人的不动
'''
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("test added")
