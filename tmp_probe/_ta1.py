# -*- coding: utf-8 -*-
import io, re
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_plan_agent.py"
t = io.open(p, encoding="utf-8", newline=None).read().replace(chr(13), "")

helper = '''def _save(agent, session):
    """2026-11-15 用户拍板「心愿单只在保存新行程/保存修改/删除时进数据库」：
    规划回合只写会话态，行在保存时物化——断言行的用例先走一次保存。"""
    agent.commit_wish_drafts(session)
    return session


'''
anchor = "def run(coro):\n"
if "_def _save(agent, session):" not in t:
    assert t.count(anchor) == 1, t.count(anchor)
    t = t.replace(anchor, helper + anchor, 1)

blocks = t.split("\ndef test_")
out = [blocks[0]]
patched = 0
for blk in blocks[1:]:
    if "svc.list_groups(" in blk and "session" in blk:
        idx = blk.index("svc.list_groups(")
        line_start = blk.rindex("\n", 0, idx) + 1
        indent = " " * (len(blk[line_start:]) - len(blk[line_start:].lstrip()))
        if "_save(agent, session)" not in blk:
            blk = blk[:line_start] + indent + "_save(agent, session)\n" + blk[line_start:]
            patched += 1
    out.append(blk)
t = "\ndef test_".join(out)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("patched tests:", patched)
