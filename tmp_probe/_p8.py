# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\plan.py"
text = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global text
    c = text.count(old)
    assert c == n, (c, old[:100])
    text = text.replace(old, new)

sub('''    itinerary_store.put(record)
    try:
        snapshot = service.create_snapshot(
''', '''    itinerary_store.put(record)
    # 2026-11-14（用户拍板「WHEN I DO NOT SAVE TRIP, 心愿单 should not be
    # saved」的对偶）：点保存 = 本会话建的心愿草稿转正（清 draft_session_id）
    # ——从这一刻起行程中心的愿望单/已排期才看得到这些行；之后再聊出来的
    # 心愿行直接是正式行（行程已在库）。
    agent.commit_wish_drafts(session)
    store.save(session)
    try:
        snapshot = service.create_snapshot(
''')

sub('''    agent.sync_removals_to_trip_items(plan_before, diffs)
''', '''    # 2026-11-14：未保存行程里新建的排除行同样是草稿（看板不显示）
    agent.sync_removals_to_trip_items(plan_before, diffs, session=session)
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(text)
print("ok", len(text))
