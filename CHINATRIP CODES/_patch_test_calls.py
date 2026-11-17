import io
p = r"D:\chinatrip\CHINATRIP CODES\tests\test_llm_no_questions.py"
with io.open(p, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()
anchor = (
    "    session, reply, change = run(agent.message(session, \"删掉外滩\"))\n"
    "    assert llm.calls == 3\n"
    "    assert \"？\" not in reply and \"?\" not in reply\n"
    "    assert \"已删除\" in reply\n"
    "    assert change is not None"
)
repl = (
    "    session, reply, change = run(agent.message(session, \"删掉外滩\"))\n"
    "    # LLM_ATTEMPTS=2：问句-only 抽签按空回复重采样一次即落地，\n"
    "    # 提问没有漏到用户面前。\n"
    "    assert llm.calls == 2\n"
    "    assert \"？\" not in reply and \"?\" not in reply\n"
    "    assert \"你想删掉哪一个景点呢\" not in reply\n"
    "    assert \"已删除\" in reply\n"
    "    assert change is not None"
)
for cand in (anchor, anchor.replace("\n", "\r\n")):
    n = src.count(cand)
    if n == 1:
        fixed = repl.replace("\n", "\r\n") if "\r\n" in cand else repl
        src = src.replace(cand, fixed)
        with io.open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
        print("test fixed")
        raise SystemExit(0)
    if n > 1:
        raise SystemExit("anchor not unique")
raise SystemExit("anchor not found")
