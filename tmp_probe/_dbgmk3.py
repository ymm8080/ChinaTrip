import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_dbg_wish.py"
t = io.open(p, encoding="utf-8").read()
t = t.replace('    n = agent.commit_wish_drafts(session)\n    print("COMMITTED", n)\n    print("BOARD", {k: [i["name"] for i in v] for k, v in svc.list_groups(iid).items() if v})',
 '    n = agent.materialize_wish_rows(session)\n    print("MATERIALIZED", n)\n    print("BOARD_AFTER_MAT", {k: [i["name"] + "|" + str(i.get("itinerary_id")) + "|" + str(i.get("status")) for i in v] for k, v in svc.list_groups().items() if v})\n    agent.sync_trip_rows(session, at_save=True)\n    print("BOARD_AFTER_SYNC", {k: [i["name"] + "|" + str(i.get("itinerary_id")) + "|" + str(i.get("status")) for i in v] for k, v in svc.list_groups().items() if v})')
io.open(p, "w", encoding="utf-8", newline="\n").write(t)
print("ok")
