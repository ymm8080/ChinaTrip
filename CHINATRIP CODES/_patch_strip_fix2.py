import io
p = r"D:\chinatrip\CHINATRIP CODES\app\services\agent\plan.py"
with io.open(p, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()
anchor = '    out = re.sub(r"[，、。！？!?；;\\s]+$", "", out)'
repl = '    # 尾部只清悬挂的分隔符（，、；），保留句号/叹号等正当句尾。\n    out = re.sub(r"[，、；;\\s]+$", "", out)'
n = src.count(anchor)
if n != 1:
    raise SystemExit(f"anchor count {n}")
src = src.replace(anchor, repl)
with io.open(p, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)
print("trailing trim narrowed")
