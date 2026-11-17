import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''    westlake.pinned = True  # user names it in the message -> pin release applies
    iid = session.plan.itinerary_id
    llm.replies.append(
        edit_reply("已删除", [{"op": "remove", "item_id": westlake.item_id}])
    )
'''.replace(chr(13), "")
new = '''    westlake.pinned = True  # user names it in the message -> pin release applies
    llm.replies.append(
        edit_reply("已删除", [{"op": "remove", "item_id": westlake.item_id}])
    )
'''.replace(chr(13), "")
assert t.count(old) == 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t.replace(old, new))
print("ok")
