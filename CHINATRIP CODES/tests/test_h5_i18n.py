"""双语 P1：H5 i18n 骨架在位测试（静态资产断言）。"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_i18n_js_exists_with_core_api():
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert "zh-CN" in js and "en" in js
    for api in ("t:", "pick:", "locale:", "setLocale:", "toggle:", "apply:"):
        assert api in js, api
    assert "ct_locale" in js  # localStorage 持久化键


def test_index_html_wired():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<script src="i18n.js"></script>' in html
    assert 'id="localeToggle"' in html
    assert 'data-i18n="nav.plan"' in html  # nav 已标记
    assert 'I18N.pick(it, "name", "name_en")' in html  # 卡片名称回退
    assert 'I18N.t("card.minutes")' in html  # 微文案已接


def test_sw_shell_includes_i18n():
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "./i18n.js" in sw  # 入壳缓存，离线可开


def test_i18n_city_dict_and_helper():
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert "CITY_EN" in js and "function city(zh)" in js
    # 主流城市覆盖（库内 204 城的主流旅游城市抽钉）
    for zh in ("北京", "上海", "西安", "成都", "张家界", "敦煌", "喀什地区喀什"):
        assert '"' + zh + '"' in js, zh
    # index.html 卡片城市可见文本走 I18N.city
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'I18N.city(it.city)' in html
