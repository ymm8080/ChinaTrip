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

src = _sub(src, "import asyncio\nimport json\n", "import asyncio\nimport json\nimport os\n\nimport pytest\n", "imports")
src = _sub(src, "def run(coro):\n    return asyncio.run(coro)\n", "def run(coro):\n    return asyncio.run(coro)\n\n\n@pytest.fixture(autouse=True)\ndef _llm_select_mode():\n    # \u7f16\u8f91\u901a\u9053\u6d4b\u8bd5\u4e0e test_plan_agent \u540c\u53e3\u5f84\uff1av0 \u8d70 LLM \u9009\u70b9\uff0c\u811a\u672c\u7b2c\n    # \u4e00\u53d1 v0_reply \u88ab start \u6d88\u8d39\uff0c\u540e\u7eed\u624d\u662f\u7f16\u8f91\u8f6e\u62bd\u7b7e\u3002\n    os.environ[\"PLAN_SELECT_MODE\"] = \"llm\"\n    yield\n    os.environ.pop(\"PLAN_SELECT_MODE\", None)\n", "fixture")
with io.open(p, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)
print("fixture added")
