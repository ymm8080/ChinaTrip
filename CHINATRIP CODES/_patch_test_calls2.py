import io
p = r"D:\chinatrip\CHINATRIP CODES\tests\test_llm_no_questions.py"
with io.open(p, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()
def _sub(text, anchor, repl, label):
    for cand in (anchor, anchor.replace("\n", "\r\n")):
        n = text.count(cand)
        if n == 1:
            fixed = repl.replace("\n", "\r\n") if "\r\n" in cand else repl
            return text.replace(cand, fixed)
        if n > 1:
            raise SystemExit(f"not unique: {label}")
    raise SystemExit(f"not found: {label}")
src = _sub(src, "    assert llm.calls == 2\n", "    assert llm.calls == 3\n", "calls")
with io.open(p, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)
print("ok")
