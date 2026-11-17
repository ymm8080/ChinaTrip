# -*- coding: utf-8 -*-
import io
wp = r"D:\tmp_ct_wishdup\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(wp, encoding="utf-8", newline=None).read()
start = t.index("        rows = [r for g in groups.values() for r in g]\n        cur_sid = self._wish_draft_session(session)\n")
end_marker = "                row = free_rows[0] if free_rows else None\n            if row is None:\n"
end = t.index(end_marker) + len(end_marker)
old_sel = '''        rows = [r for g in groups.values() for r in g]
        for item in planned:
            row = next(
                (
                    r
                    for r in rows
                    if (item.poi_id and r.get("poi_id") and r["poi_id"] == item.poi_id)
                    or _name_dup(str(r.get("name") or ""), item.name)
                ),
                None,
            )
            if row is None:
'''
t = t[:start] + old_sel + t[end:]
io.open(wp, "w", encoding="utf-8", newline="\r\n").write(t)
print("reverted (c) in worktree")
