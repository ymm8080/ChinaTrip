# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions\w12_0035_trip_item_drafts.py"
raw = io.open(p, encoding="utf-8", newline="").read()
lines = raw.split("\n")
out = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.strip() == "VIEW_PLAIN = VIEW_WITH_DRAFT_FILTER.replace(":
        out.append(line)
        out.append('    "        WHERE t.draft_session_id IS NULL' + chr(92) + 'n", ""')
        # skip the broken continuation lines until the closing paren line
        i += 1
        while i < len(lines) and lines[i].strip() != ")":
            i += 1
        out.append(")")
        i += 1
        continue
    out.append(line)
    i += 1
io.open(p, "w", encoding="utf-8", newline="").write("\n".join(out))
print("fixed")
