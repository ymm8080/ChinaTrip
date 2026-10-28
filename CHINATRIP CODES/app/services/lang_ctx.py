"""请求级 UI 语言上下文：H5 每个请求带 X-Lang: en|zh（i18n locale 同步），
LangMiddleware 写入 contextvar，服务层用 L(zh, en) 取当前语言的文案。
默认 zh——无请求上下文的路径（jobs、LLM 提示词、日志）行为与迁移前一致。"""

from __future__ import annotations

import contextvars

_lang: contextvars.ContextVar[str] = contextvars.ContextVar("ui_lang", default="zh")


def set_lang(value: str | None) -> None:
    _lang.set("en" if (value or "").strip().lower() == "en" else "zh")


def get_lang() -> str:
    return _lang.get()


def is_en() -> bool:
    return _lang.get() == "en"


def L(zh: str, en: str) -> str:
    return en if _lang.get() == "en" else zh
