"""X-Lang 头 → contextvar → L(zh, en) 选文：P3 后端双语的基础设施。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.lang import LangMiddleware
from app.services import lang_ctx
from app.services.lang_ctx import L, set_lang


def test_l_picks_by_contextvar():
    set_lang("en")
    assert L("中文", "English") == "English"
    set_lang("zh")
    assert L("中文", "English") == "中文"


def test_set_lang_normalizes_junk():
    set_lang("  EN ")
    assert lang_ctx.get_lang() == "en"
    set_lang(None)
    assert lang_ctx.get_lang() == "zh"
    set_lang("fr")
    assert lang_ctx.get_lang() == "zh"


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(LangMiddleware)

    @app.get("/probe")
    def probe():
        return {"lang": lang_ctx.get_lang(), "text": L("你好", "hello")}

    return TestClient(app)


def test_middleware_reads_x_lang_header():
    r = _client().get("/probe", headers={"X-Lang": "en"})
    assert r.json() == {"lang": "en", "text": "hello"}


def test_middleware_defaults_zh_without_header():
    r = _client().get("/probe")
    assert r.json() == {"lang": "zh", "text": "你好"}
