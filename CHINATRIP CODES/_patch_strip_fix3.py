import io
p = r"D:\chinatrip\CHINATRIP CODES\app\services\agent\plan.py"
with io.open(p, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()
anchor = (
    "    out = re.sub(\n"
    "        r\"[^。！？!?；;\\n]*[？?][^。！？!?；;\\n]*[。！？!?；;\\n]?\",\n"
    "        \"\",\n"
    "        probe,\n"
    "    )"
)
repl = (
    "    out = re.sub(r\"[^。！？!?；;\\n]*[？?]\", \"\", probe)"
)
for cand in (anchor, anchor.replace("\n", "\r\n")):
    n = src.count(cand)
    if n == 1:
        fixed = repl.replace("\n", "\r\n") if "\r\n" in cand else repl
        src = src.replace(cand, fixed)
        with io.open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
        print("pattern fixed")
        raise SystemExit(0)
    if n > 1:
        raise SystemExit(f"anchor not unique: {n}")
raise SystemExit("anchor not found")
