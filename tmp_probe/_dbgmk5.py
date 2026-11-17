import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_dbg2.py"
t = io.open(p, encoding="utf-8").read()
t = t.replace('    agent.commit_wish_drafts(session)', '''    import asyncio
    notes2, unresolved2 = asyncio.run(
        agent.sync_wishes_to_trip_items(session, ["蜀风雅韵"], user_texts=["我要去蜀风雅韵"])
    )
    print("DIRECT_SYNC", notes2, unresolved2, session.wish_sources)
    agent.commit_wish_drafts(session)''')
io.open(p, "w", encoding="utf-8", newline="\n").write(t)
print("ok")
