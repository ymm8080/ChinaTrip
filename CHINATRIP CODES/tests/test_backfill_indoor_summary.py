"""回填作业测试：indoor/rain（B2）+ review_summary（D3）。"""

import asyncio

from app.jobs.backfill_indoor_rain import (
    _process_row,
    backfill,
    classify_indoor,
    parse_verdict,
)
from app.jobs.backfill_review_summary import validate_summary


class _Row:
    def __init__(self, name, category=None, indoor=None, rain_ok=None):
        self.name_zh = name
        self.category = category
        self.indoor = indoor
        self.rain_ok = rain_ok


def test_classify_indoor_heuristics():
    assert classify_indoor("三峡博物馆", None) == "yes"
    assert classify_indoor("武隆天生三桥", "风景名胜") == "no"
    assert classify_indoor("上海迪士尼乐园", None) == "partial"
    assert classify_indoor("某某观景台", None) is None


def test_backfill_indoor_only_fills_empty():
    rows = [
        _Row("三峡博物馆"),  # 填 yes/yes
        _Row("洪崖洞", indoor="no"),  # 已有值跳过
        _Row("无名地"),  # 未判定 unmatched
    ]
    written = []

    def writer(row, indoor, rain):
        written.append((row.name_zh, indoor, rain))

    stats = backfill(rows, writer=writer)
    assert written == [("三峡博物馆", "yes", "yes")]
    assert stats["filled"] == 1
    assert stats["skipped_existing"] == 1
    assert stats["unmatched"] == 1


def test_validate_summary_five_gates():
    assert validate_summary("游客普遍称赞夜景震撼，适合傍晚前往拍照") is not None
    assert validate_summary(None) is None
    assert validate_summary("太短") is None  # 长度下限
    assert validate_summary("好" * 80) is None  # 长度上限
    assert validate_summary("详情见 https://example.com 的攻略") is None  # URL
    assert validate_summary("作为一个AI语言模型我无法评价这个景点") is None  # 自指
    assert validate_summary("great place to visit ok") is None  # 无中文占位


def test_review_summary_job_skips_on_mock_backend(monkeypatch):
    import app.jobs.backfill_review_summary as mod

    class _Settings:
        llm_backend = "mock"

    monkeypatch.setattr(mod, "get_settings", lambda: _Settings())

    # main 应直接 skip 不触碰 DB/LLM
    assert mod.main([]) == 0


# --- indoor/rain llm 层（--stage llm，2026-10-25） ---------------------------


def test_parse_verdict_prefix_and_skip():
    assert parse_verdict("室内") == "yes"
    assert parse_verdict("露天") == "no"
    assert parse_verdict("混合") == "partial"
    assert parse_verdict("室内\n\n(Note: 大部分展厅在室内)") == "yes"  # 前缀容错
    assert parse_verdict("SKIP") == "skip"
    assert parse_verdict("SKIP\n\n(Note: unknown place)") == "skip"
    assert parse_verdict("") is None
    assert parse_verdict(None) is None
    assert parse_verdict("我觉得应该是室内吧") is None  # 非法格式拒绝


class _FakeResult:
    def __init__(self, content):
        self.content = content
        self.tokens_in = 10
        self.tokens_out = 5


class _FakeAdapter:
    def __init__(self, content="露天"):
        self.content = content
        self.calls = 0

    async def chat(self, messages, temperature=0.3, max_tokens=1024):
        self.calls += 1
        return _FakeResult(self.content)


class _LLMRow:
    """模拟 ORM Poi 行（llm 层目标：indoor/rain_ok 任一为空）。"""

    def __init__(self, name, category=None, indoor=None, rain_ok=None):
        self.id = hash(name)
        self.name_zh = name
        self.city = "测试市"
        self.category = category
        self.indoor = indoor
        self.rain_ok = rain_ok


def _run(row, adapter, writes):
    def _fake_write(session_factory, poi_id, indoor, rain):
        writes.append((row.name_zh, indoor, rain))
        return True

    import app.jobs.backfill_indoor_rain as mod

    stats = {
        "filled": 0,
        "skipped": 0,
        "skipped_existing": 0,
        "rejected": 0,
        "errors": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    sem = asyncio.Semaphore(2)
    monkey_write = _fake_write
    old = mod._write_columns
    mod._write_columns = monkey_write
    try:
        asyncio.run(_process_row(adapter, None, row, sem, stats))
    finally:
        mod._write_columns = old
    return stats


def test_llm_stage_heuristic_free_path():
    # 启发式可判 yes/no → 不调 LLM 直接填（零成本路径）
    adapter = _FakeAdapter()
    writes = []
    stats = _run(_LLMRow("三峡博物馆"), adapter, writes)
    assert adapter.calls == 0
    assert writes == [("三峡博物馆", "yes", "yes")]
    assert stats["filled"] == 1


def test_llm_stage_partial_goes_llm():
    # partial 走 LLM 精化（docstring 口径：partial/未命中行 LLM）
    adapter = _FakeAdapter(content="露天")
    writes = []
    _run(_LLMRow("上海迪士尼乐园"), adapter, writes)
    assert adapter.calls == 1
    assert writes == [("上海迪士尼乐园", "no", "no")]


def test_llm_stage_rejects_garbage_fill_empty():
    # LLM 乱回 → 拒绝且不写库（只填空铁律：宁缺勿错）
    adapter = _FakeAdapter(content="我觉得是室内")
    writes = []
    stats = _run(_LLMRow("某某观景台"), adapter, writes)
    assert writes == []
    assert stats["rejected"] == 1


def test_llm_stage_llm_error_counts_not_raises():
    class _Boom:
        async def chat(self, *a, **k):
            raise RuntimeError("timeout")

    writes = []
    stats = _run(_LLMRow("无名地"), _Boom(), writes)
    assert writes == []
    assert stats["errors"] == 1
