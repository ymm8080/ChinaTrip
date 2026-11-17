import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_dbg2.py"
t = io.open(p, encoding="utf-8").read()
t = t.replace('    llm.replies.append(edit_reply("已加入", [_ADD_FACE_SHOW], wishes=["蜀风雅韵"]))', '''    _orig = agent.sync_wishes_to_trip_items

    async def _spy(session_, wishes_, **kw):
        print("SYNC_CALLED", wishes_, kw)
        return await _orig(session_, wishes_, **kw)

    agent.sync_wishes_to_trip_items = _spy
    llm.replies.append(edit_reply("已加入", [_ADD_FACE_SHOW], wishes=["蜀风雅韵"]))''')
io.open(p, "w", encoding="utf-8", newline="\n").write(t)
print("ok")
