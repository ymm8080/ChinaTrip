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
