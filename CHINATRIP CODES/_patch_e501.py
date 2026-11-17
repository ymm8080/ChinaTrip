import io
p = r"D:\chinatrip\CHINATRIP CODES\tests\test_llm_no_questions.py"
with io.open(p, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()
old = (
    "    # 没有问句原样返回\n"
    "    assert _strip_llm_questions(\"已删除外滩，行程已更新。\") == \"已删除外滩，行程已更新。\"\n"
    "    assert _strip_llm_questions(\"\") == \"\"\n"
    "    assert _strip_llm_questions(\"All done — moved to day 2!\") == \"All done — moved to day 2!\"\n"
)
new = (
    "    # 没有问句原样返回\n"
    "    clean = \"已删除外滩，行程已更新。\"\n"
    "    assert _strip_llm_questions(clean) == clean\n"
    "    assert _strip_llm_questions(\"\") == \"\"\n"
    "    done = \"All done - moved to day 2!\"\n"
    "    assert _strip_llm_questions(done) == done\n"
)
for cand in (old, old.replace("\n", "\r\n")):
    n = src.count(cand)
    if n == 1:
        fixed = new.replace("\n", "\r\n") if "\r\n" in cand else new
        src = src.replace(cand, fixed)
        with io.open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
        print("e501 fixed")
        raise SystemExit(0)
    if n > 1:
        raise SystemExit("not unique")
raise SystemExit("anchor not found")
