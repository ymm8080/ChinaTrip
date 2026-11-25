"""确认卡站点英文名（2026-11-25 用户实报「选英文时贴文读出的站点还是中文」）。

EN 语言下：确认卡问句列表（_site_confirm_question）与 api 组包
（site_names_en payload / _plan_turn_body）都按库内英文名显示
（display_names_en：name_zh 精确 + JSONB 别名承接）；zh 请求零变化；
英文名只是显示糖——pending_sites/must/确认提交等数据层保持中文名。
"""

from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.lang_ctx import set_lang
from app.services.poi_details import PoiDetailStore

ROWS = [
    {
        "name": "故宫博物院",
        "name_en": "The Palace Museum",
        "name_aliases": ["紫禁城", "Forbidden City"],
        "status": "active",
    },
    {
        "name": "天坛",
        "name_en": "Temple of Heaven",
        "name_aliases": [],
        "status": "active",
    },
    {
        "name": "鸟巢(国家体育场)",
        "name_en": "Bird's Nest (National Stadium)",
        "name_aliases": ["国家体育场"],
        "status": "active",
    },
    {
        "name": "天安门广场",
        "name_en": "",
        "name_aliases": [],
        "status": "active",
    },
]


class EnMemoryStore(PoiDetailStore):
    """内存底库桩：_memory 行手工带 name_en/name_aliases（内存路语义）。"""

    def __init__(self, rows):
        super().__init__()
        for i, r in enumerate(rows):
            self._memory[f"probe-{i}"] = dict(r)


class ExplodingLLM:
    name = "explode"

    async def chat(self, messages, **kwargs):
        raise AssertionError("LLM must not be called here")


def _agent(store):
    return PlanningAgent(ExplodingLLM(), poi_details=store)


def _session(sites):
    return PlanSession(
        session_id="probe-s",
        device_id="probe-dev",
        state="site_confirm",
        pending_sites=list(sites),
        cities=["北京"],
        days=3,
        pending_sites_source="brief",
    )


def test_display_names_en_exact_and_alias():
    store = EnMemoryStore(ROWS)
    m = store.display_names_en(["故宫博物院", "天坛", "国家体育场"])
    assert m["故宫博物院"] == "The Palace Museum"
    assert m["天坛"] == "Temple of Heaven"
    # 别名承接：确认卡上的「国家体育场」由 鸟巢(国家体育场) 行接住
    assert m["国家体育场"] == "Bird's Nest (National Stadium)"


def test_display_names_en_missing_and_empty_en_fall_back():
    store = EnMemoryStore(ROWS)
    m = store.display_names_en(["天安门广场", "不认识的地方"])
    # 行在但 name_en 空 → 不写（调用方回落中文名，不硬凑）
    assert "天安门广场" not in m
    assert "不认识的地方" not in m
    # 空输入与重复名安全
    assert store.display_names_en([]) == {}
    assert store.display_names_en(["天坛", " 天坛 "])["天坛"] == "Temple of Heaven"


def test_confirm_question_en_uses_english_names():
    agent = _agent(EnMemoryStore(ROWS))
    s = _session(["故宫博物院", "天坛", "国家体育场"])
    set_lang("en")
    try:
        q = agent._site_confirm_question(s, source="brief")
    finally:
        set_lang("zh")
    assert "The Palace Museum" in q
    assert "Temple of Heaven" in q
    assert "Bird's Nest (National Stadium)" in q
    assert "故宫博物院" not in q
    assert "天坛（" not in q  # 中文站名不出现在列表里


def test_confirm_question_zh_unchanged():
    agent = _agent(EnMemoryStore(ROWS))
    s = _session(["故宫博物院", "天坛"])
    q = agent._site_confirm_question(s, source="brief")
    assert "故宫博物院" in q
    assert "天坛" in q
    assert "The Palace Museum" not in q


def test_confirm_question_no_store_falls_back_to_chinese():
    agent = _agent(None)
    s = _session(["故宫博物院"])
    set_lang("en")
    try:
        q = agent._site_confirm_question(s, source="brief")
    finally:
        set_lang("zh")
    # 无 store（或查询失败）→ 空表回落中文名，绝不因显示层挂掉问句
    assert "故宫博物院" in q


def test_site_names_en_payload_lang_switch(monkeypatch):
    from app.api.plan import _site_names_en_payload

    monkeypatch.setattr(
        "app.api.plan.get_poi_detail_store", lambda: EnMemoryStore(ROWS)
    )
    s = _session(["故宫博物院", "国家体育场"])
    set_lang("en")
    try:
        p = _site_names_en_payload(s)
    finally:
        set_lang("zh")
    assert p["故宫博物院"] == "The Palace Museum"
    assert p["国家体育场"] == "Bird's Nest (National Stadium)"
    # zh 请求直接空表（零开销）
    assert _site_names_en_payload(s) == {}
    # 无站点会话安全
    assert _site_names_en_payload(_session([])) == {}


def test_plan_turn_body_carries_site_names_en(monkeypatch):
    from app.api.plan import _plan_turn_body

    monkeypatch.setattr(
        "app.api.plan.get_poi_detail_store", lambda: EnMemoryStore(ROWS)
    )
    s = _session(["故宫博物院", "天坛"])
    set_lang("en")
    try:
        body = _plan_turn_body(s, "reply text", None)
    finally:
        set_lang("zh")
    assert body["state"] == "site_confirm"
    assert body["sites"] == ["故宫博物院", "天坛"]  # 数据层仍中文名
    assert body["site_names_en"]["故宫博物院"] == "The Palace Museum"
    assert body["site_names_en"]["天坛"] == "Temple of Heaven"
    set_lang("zh")
    body = _plan_turn_body(s, "reply text", None)
    assert body["site_names_en"] == {}


def test_h5_frontend_reads_site_names_en():
    """前端静态断言（R27 惯例兜底）：chips 与回复句都消费 site_names_en。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    # chips label 与 siteReplyNode 两处消费 + EN 判定共用 I18N.locale()
    assert html.count("site_names_en") >= 3
    assert html.count('I18N.locale() !== "zh"') >= 2
    sw = (root / "app" / "static" / "sw.js").read_text(encoding="utf-8")
    # 版本号每次前端改动都会递增（取 max+1）：断言下限而非钉死某个值——
    # 否则别人下一次 bump 就把本测试打红（R39 交通腿统一 bump v144 实锤）。
    import re

    m = re.search(r"const VERSION = 'v(\d+)';", sw)
    assert m and int(m.group(1)) >= 143
