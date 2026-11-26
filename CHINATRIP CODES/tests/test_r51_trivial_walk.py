# -*- coding: utf-8 -*-
"""R51：同址 0 公里/1 分钟步行腿不显示（页脚与桥卡同一判定）。"""

from pathlib import Path


def _html() -> str:
    return (
        Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"
    ).read_text(encoding="utf-8")


def test_h5_trivial_walk_row_hidden():
    """用户令「0.0 km · 步行约 1 分钟 这个不用显示出来」：页脚与桥卡两处都闸。"""
    html = _html()
    assert "const trivialLeg = (x) => {" in html
    assert '(mode === "walk" || mode === "same_venue")' in html
    assert "if (hasKm && !isBridgeCard && !bridgeFollows && !trivialLeg(it)) {" in html
    assert (
        "const brRow = isBridgeCard && !trivialLeg(it) ? "
        "legRowParts(it, d.items, idx) : null;" in html
    )


def test_h5_trivial_walk_keeps_real_legs():
    """判定只吃 0km/1 分钟：真实步行/打车/接驳腿不受影响。"""
    html = _html()
    assert "km < 0.05" in html
    assert "min <= 1" in html


def test_h5_trivial_leg_declared_before_first_use():
    """TDZ 守门：const trivialLeg 必须在首次 trivialLeg(it) 引用之前定义。

    2026-11-26 用户实报「数据已返回但渲染中断：Cannot access 'trivialLeg'
    before initialization」——定义被挪到 brRow 引用之后，const 暂时性死区
    在渲染期抛 ReferenceError，整页卡死。只查字符串存在的旧测试漏掉了顺序。
    """
    html = _html()
    decl = html.index("const trivialLeg = (x) => {")
    first_use = html.index("trivialLeg(it)")
    assert decl < first_use, (
        "trivialLeg 定义在首次使用之后（TDZ）：decl=%d first_use=%d" % (decl, first_use)
    )
