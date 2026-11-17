"""请求级 UI 语言上下文：H5 每个请求带 X-Lang（i18n locale 短码同步），
LangMiddleware 写入 contextvar，服务层用 L(zh, en, …) 按位置取当前语言的文案。
默认 zh——无请求上下文的路径（jobs、LLM 提示词、日志）行为与迁移前一致。

多语言机制（DESIGN language_nlang_switch_design_2026-11-03 §2.1）：
- SUPPORTED 位置制——zh=0 / en=1 位置永久冻结，新语言只 append；
- L(*texts) 走 requested→en→zh 回退链按 SUPPORTED 位置取词：既有两参调用
  零改动即可上线新语言（缺位自动回退 en），某串要 L2 专属译法时在调用点补位参；
- set_lang 做 BCP47 折叠（zh-CN→zh、en-US→en、ja-JP→ja…），未知码归 DEFAULT_LANG。
"""

from __future__ import annotations

import contextvars

# 位置制语言注册表：zh=0 / en=1 永久冻结，新语言只 append（design §2.1）。
# 与前端 i18n.js DICT / LANGS 顶层键保持一致（tests/test_lang_sync.py 机器把关防分叉）。
SUPPORTED: tuple[str, ...] = ("zh", "en", "ja", "ko")
DEFAULT_LANG = "zh"

# BCP47 折叠表：常见地区/文字子标签变体 → 短码；表外变体取主子标签再认
_FOLD: dict[str, str] = {
    "zh": "zh",
    "zh-cn": "zh",
    "zh-sg": "zh",
    "zh-hans": "zh",
    "zh-hans-cn": "zh",
    "zh-tw": "zh",
    "zh-hk": "zh",
    "zh-mo": "zh",
    "zh-hant": "zh",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "en-sg": "en",
    "ja": "ja",
    "ja-jp": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "ko-kp": "ko",
}

_lang: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ui_lang", default=DEFAULT_LANG
)


def normalize_lang(value: str | None) -> str:
    """BCP47 折叠到 SUPPORTED 短码：'  EN '→en、zh-CN→zh、ja-JP→ja；未知→zh。"""
    v = (value or "").strip().lower()
    if not v:
        return DEFAULT_LANG
    if v in _FOLD:
        return _FOLD[v]
    primary = v.split("-")[0]  # fr-CA 类表外变体取主子标签，命中 SUPPORTED 才认
    return primary if primary in SUPPORTED else DEFAULT_LANG


def set_lang(value: str | None) -> None:
    _lang.set(normalize_lang(value))


def get_lang() -> str:
    return _lang.get()


def lang_chain(lang: str | None = None) -> tuple[str, ...]:
    """展示回退链（design §2.2）：zh 恒 [zh]（L1 全量，缺词由守门 zh 词条门把关）；
    其余 requested→en→zh——骨架语言缺词落英文（pivot），en 再缺落 zh（与改造前
    en→zh 兜底一致）。"""
    cur = normalize_lang(lang) if lang is not None else _lang.get()
    if cur == "zh":
        return ("zh",)
    return ("en", "zh") if cur == "en" else (cur, "en", "zh")


def is_en() -> bool:
    """二元内容分叉位（read-side EN 翻译 / EN 页面壳）：非 zh 一律走 en 内容——
    pivot en 质量最优，且 L2/L3 用户的浏览器整页翻译源文本即 en（design §0/§3.3）。"""
    return _lang.get() != "zh"


def L(*texts: str) -> str:
    """位置制选文：L(zh, en) 两参语义不变；新语言专属译法在调用点补位参
    （如 L(zh, en, ja)）。requested 链按 SUPPORTED 位置取词，缺位自动回退。"""
    for code in lang_chain():
        i = SUPPORTED.index(code)
        if i < len(texts):
            return texts[i]
    return texts[0]
