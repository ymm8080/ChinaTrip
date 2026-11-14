"""X-Lang 头 → contextvar → L(zh, en) 选文：P3 后端双语的基础设施。
多语言机制（design nlang §2.1）：位置制 L(*texts) + SUPPORTED 注册表 + BCP47
归一 + requested→en→zh 回退链——既有两参调用零改动，新语言只 append。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.lang import LangMiddleware
from app.services import lang_ctx
from app.services.lang_ctx import SUPPORTED, L, lang_chain, normalize_lang, set_lang


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


def test_normalize_lang_bcp47_folds():
    # design §2.1：zh-CN/zh-TW→zh、en-US→en、ja-JP→ja；未知码归 DEFAULT_LANG
    assert normalize_lang("zh-CN") == "zh"
    assert normalize_lang("zh-TW") == "zh"
    assert normalize_lang("zh-Hans-CN") == "zh"
    assert normalize_lang("en-US") == "en"
    assert normalize_lang("ja") == "ja"
    assert normalize_lang("ja-JP") == "ja"
    assert normalize_lang("ko-KR") == "ko"
    assert normalize_lang("de-DE") == "zh"  # 表外主子标签不认，归默认
    assert normalize_lang("") == "zh"
    assert normalize_lang(None) == "zh"
    # 中间件/分享页 ?lang= 共用同一归一化函数
    set_lang("zh-CN")
    assert lang_ctx.get_lang() == "zh"
    set_lang("ja-JP")
    assert lang_ctx.get_lang() == "ja"


def test_lang_chain_fallback_order():
    set_lang("zh")
    assert lang_chain() == ("zh",)
    set_lang("en")
    assert lang_chain() == ("en", "zh")
    set_lang("ja")
    assert lang_chain() == ("ja", "en", "zh")  # 骨架语言缺词落英文（pivot）
    set_lang("ko")
    assert lang_chain() == ("ko", "en", "zh")


def test_l_two_arg_calls_unchanged_for_new_langs():
    # design §2.1 铁律：257 处既有 L(zh, en) 两参调用零改动——ja/ko 缺位自动回退 en
    set_lang("ja")
    assert L("中文", "English") == "English"
    set_lang("ko")
    assert L("中文", "English") == "English"
    set_lang("zh-CN")
    assert L("中文", "English") == "中文"


def test_l_positional_third_arg_for_l2_language():
    # 某串要 L2 专属译法时仅在那一处补位参：L(zh, en, ja)——SUPPORTED 位置制
    assert SUPPORTED.index("zh") == 0 and SUPPORTED.index("en") == 1  # 冻结位
    set_lang("ja")
    assert L("中文", "English", "日本語") == "日本語"
    set_lang("ko")  # ko 位（3）缺第三参之后没有文本 → 回退 en 位（1）
    assert L("中文", "English", "日本語") == "English"
    set_lang("en")
    assert L("只有中文") == "只有中文"  # 单参调用任何语言都回位 0


def test_is_en_rides_en_content_for_non_zh():
    # design §3.3：非 zh 一律走 en 内容（pivot en = L2/L3 浏览器翻译源文本）
    set_lang("ja")
    assert lang_ctx.is_en() is True
    set_lang("ko")
    assert lang_ctx.is_en() is True
    set_lang("zh")
    assert lang_ctx.is_en() is False


def test_supported_registered_in_backend():
    assert set(("zh", "en", "ja", "ko")) == set(SUPPORTED)


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


def test_middleware_passes_skeleton_shortcodes():
    r = _client().get("/probe", headers={"X-Lang": "ja"})
    assert r.json() == {"lang": "ja", "text": "hello"}  # 缺位回退 en
    r = _client().get("/probe", headers={"X-Lang": "zh-CN"})
    assert r.json() == {"lang": "zh", "text": "你好"}
