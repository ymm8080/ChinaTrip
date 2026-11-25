# -*- coding: utf-8 -*-
"""R42：必去确认卡「迟到的确认」不再出死横幅——回落消息通道续排（静态断言）。

用户令（2026-11-25）：ℹ️「这轮必去确认已经结束…」提示不许再出现；迟到的
确认要把勾选的地点继续排下去。修法（纯前端）：
1) planConfirmSites 的 not_awaiting_sites 分支：删死横幅，勾选地点自动拼
   消息走 planSend（后端慢车道/主车道本就会续排）；没勾就静默收卡。
2) planSend 加可选 presetText，预置路径不清用户输入框。
3) planRenderReply 开新确认卡前先失效旧卡（旧 ✅ 跨轮可点是横幅主产口）。
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_late_confirm_dead_banner_gone():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '"plan.sites.late"' not in html  # 旧死横幅键不再被引用
    assert "这轮必去确认已经结束" not in html  # 用户令：这条提示不许出现


def test_late_confirm_falls_through_to_message_lane():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    # 迟到分支：收卡 + 回落 planSend（勾选地点转消息续排）
    assert 'planSend(I18N.tf("plan.sites.lateSend"' in html
    assert "@SITES@" in html
    assert "plan.sites.lateSend" in (STATIC / "i18n.js").read_text(encoding="utf-8")


def test_plan_send_supports_preset_without_touching_input():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "async function planSend(presetText)" in html
    body = html[html.index("async function planSend(presetText)") :]
    body = body[: body.index("async function planPollSlowTask")]
    # 预置文本取参不取输入框；预置路径不清输入框（草稿是用户自己的）
    assert "presetText === undefined || presetText === null ? input.value" in body
    assert (
        body.count(
            'if (presetText === undefined || presetText === null) input.value = "";'
        )
        >= 1
    )


def test_new_confirm_round_retires_old_boxes():
    with (STATIC / "index.html").open(encoding="utf-8", newline="") as f:  # 保留 CRLF
        html = f.read()
    anchor = (
        'if (body.state === "site_confirm" && (body.sites || []).length) {\r\n'
        "    closeSiteChipBoxes();"
    )
    assert anchor in html


def test_i18n_dead_key_removed():
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert '"plan.sites.lateSend":' in js
    assert '"plan.sites.late":' not in js


def test_sw_bumped_with_changelog():
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    m = re.search(r"const VERSION = 'v(\d+)';", sw)
    assert m, "VERSION line missing"
    # 下限不钉死：并行会话会继续 bump（R39 教训），本轮底线 v152
    assert int(m.group(1)) >= 152
    assert "v152 2026-11-25" in sw  # 本轮 changelog 行在案
