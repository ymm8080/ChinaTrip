"""前后端语言注册表同步钉（design nlang §6 风险1）：pytest 解析 app/static/i18n.js，
断言后端 SUPPORTED ⊆ 前端 DICT / LANGS 顶层键——两侧分叉（注册表各改各的）在 CI
即拦下，防「后端认了语言、前端词典缺顶层键」的静默回退事故。"""

import re
from pathlib import Path

from app.services import lang_ctx

I18N_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "i18n.js"


def _top_keys(anchor: str, end_anchor: str, pattern: str) -> set[str]:
    src = I18N_JS.read_text(encoding="utf-8")
    seg = src[src.index(anchor) : src.index(end_anchor)]
    return set(re.findall(pattern, seg, re.M))


def _dict_keys() -> set[str]:
    # DICT 顶层键：`    "zh": {` 形态（4 空格缩进 + 值为词典），区间止于 CITY_EN
    return _top_keys("var DICT = {", "var CITY_EN", r'^    "([A-Za-z-]+)": \{$')


def _langs_keys() -> set[str]:
    # LANGS 条目为单行对象（`    "zh": { htmlTag: … }`），锚定行首键即可
    return _top_keys("var LANGS = {", "var KEY =", r'^    "([a-z-]+)": \{')


def test_supported_subset_of_frontend_dict():
    missing = set(lang_ctx.SUPPORTED) - _dict_keys()
    assert not missing, f"i18n.js DICT 缺后端 SUPPORTED 语言键: {sorted(missing)}"


def test_supported_subset_of_frontend_langs():
    missing = set(lang_ctx.SUPPORTED) - _langs_keys()
    assert not missing, f"i18n.js LANGS 缺后端 SUPPORTED 语言键: {sorted(missing)}"
