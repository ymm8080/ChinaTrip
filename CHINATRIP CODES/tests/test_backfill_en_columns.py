"""双语 P1：_en 翻译回填作业测试（backfill_en_columns）。"""

import asyncio

from app.jobs.backfill_en_columns import (
    parse_tags_json,
    validate_translation,
)


def test_validate_translation_gates():
    assert (
        validate_translation("Palace Museum, a vast complex", source="故宫博物院")
        is None
    )
    assert validate_translation("a", source="x") == "too_short"  # 长度下限
    assert validate_translation("x" * 601, source="x") == "too_long"
    assert (  # 中文主体
        validate_translation("这是一个很好的地方", source="故宫") == "no_latin"
    )
    assert (  # 原文复读且非拉丁
        validate_translation("故宫博物院", source="故宫博物院") == "no_latin"
    )
    assert validate_translation("see https://x.com ok", source="看这里") == "meta"
    assert validate_translation("Palace Museum", source="Palace Museum") == "echo"


def test_parse_tags_json():
    assert parse_tags_json('["Great history", "Kid-friendly"]') == [
        "Great history",
        "Kid-friendly",
    ]
    assert parse_tags_json("not json") is None
    assert parse_tags_json('{"a": 1}') is None  # 非数组
    assert parse_tags_json('["好景点"]') is None  # 含中文标签拒
    assert parse_tags_json("[]") is None  # 空
    assert parse_tags_json(None) is None


class _FakeResult:
    def __init__(self, content):
        self.content = content
        self.tokens_in = 10
        self.tokens_out = 5


class _FakeAdapter:
    """按 (kind, source) 映射返回译文的假适配器。"""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    async def chat(self, messages, temperature=0.2, max_tokens=1024):
        user = messages[1].content
        self.calls.append(user)
        for key, val in self.mapping.items():
            if key in user:
                return _FakeResult(val)
        return _FakeResult("SKIP")


class _EnRow:
    def __getattr__(self, name):
        # FIELD_SPECS 扩列后（P1.5）假行未逐个声明的源/目标列按 NULL 处理
        return None

    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.name_zh = kw.get("name_zh", "故宫")
        self.name_en = kw.get("name_en")
        self.intro = kw.get("intro")
        self.intro_en = kw.get("intro_en")
        self.address = kw.get("address")
        self.address_en = kw.get("address_en")
        self.review_tags = kw.get("review_tags")
        self.review_tags_en = kw.get("review_tags_en")
        self.rating_count = 100
        # FIELD_SPECS 扩列后的 kwarg 通配写入（如 opening_hours）
        for k, v in kw.items():
            if k not in self.__dict__:
                setattr(self, k, v)


def _run(row, adapter, table="pois"):
    """驱动 _process_row，写库走内存 updates 捕获。"""
    import app.jobs.backfill_en_columns as mod

    writes = []

    def fake_write(session_factory, model, row_id, updates):
        writes.append(updates)
        return bool(updates)

    stats = {
        "rows_filled": 0,
        "fields_filled": 0,
        "skipped": 0,
        "rejected": 0,
        "rejected_by_reason": {},
        "errors": 0,
        "template": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    old = mod._write_row
    mod._write_row = fake_write
    try:
        asyncio.run(
            mod._process_row(adapter, None, row, table, asyncio.Semaphore(2), stats)
        )
    finally:
        mod._write_row = old
    return stats, writes


def test_process_row_translates_text_and_tags():
    adapter = _FakeAdapter(
        {
            "把以下中文译成英文：故宫": "The Forbidden City",
            "把以下中文译成英文：明清两代皇宫": "Imperial palace of Ming and Qing",
            "点评标签数组": '["Historic", "World heritage"]',
        }
    )
    row = _EnRow(
        name_zh="故宫",
        intro="明清两代皇宫",
        address="北京市东城区景山前街4号",
        review_tags=["历史厚重"],
    )
    # 注意：address 源文本未在 mapping → SKIP 分支
    stats, writes = _run(row, adapter)
    assert adapter.calls  # 至少 name/intro/tags 三类调用
    assert stats["errors"] == 0
    assert writes, "应有写库"
    merged = {}
    for w in writes:
        merged.update(w)
    assert merged["name_en"] == "The Forbidden City"
    assert merged["intro_en"].startswith("Imperial palace")
    assert merged["review_tags_en"] == ["Historic", "World heritage"]


def test_process_row_skip_keeps_empty_and_never_overwrites():
    adapter = _FakeAdapter({})  # 全部 SKIP
    row = _EnRow(intro="某某馆简介", name_en="Already Set")
    stats, writes = _run(row, adapter)
    # name_en 已有值不再请求（只填空）；intro SKIP → 不写
    assert all("name_en" not in w for w in writes)
    assert stats["skipped"] >= 1


def test_process_row_rejects_garbage():
    adapter = _FakeAdapter({"把以下中文译成英文：某某馆简介": "这是一个很好的地方"})
    row = _EnRow(intro="某某馆简介")
    stats, writes = _run(row, adapter)
    assert writes == []
    assert stats["rejected"] == 1


def test_template_hours_en():
    from app.jobs.backfill_en_columns import template_hours_en

    assert template_hours_en("周一至周日 08:30-17:00") == "Monday–Sunday 08:30-17:00"
    assert template_hours_en("周一闭馆") == "Monday Closed"
    assert (
        template_hours_en("周二至周日 09:00-16:30，周一闭馆")
        == "Tuesday–Sunday 09:00-16:30, Monday Closed"
    )
    assert template_hours_en("星期一 不开放") == "Monday Closed"
    assert template_hours_en("周日全天") == "Sunday All day"
    assert template_hours_en("法定节假日除外") == "except public holidays"
    assert template_hours_en("旺季（4月-10月）08:00") is None  # 残句→LLM 兜底
    assert template_hours_en(None) is None


def test_template_hours_en_extended_vocab():
    """2026-10-30 扩词表：残句高频表述确定性覆盖，数字零改动。"""
    from app.jobs.backfill_en_columns import template_hours_en as t

    # 停止入园/检票/最晚进入 → last entry
    assert (
        t("周一至周日 08:30-17:00 最晚进入15:30")
        == "Monday–Sunday 08:30-17:00 last entry 15:30"
    )
    assert t("09:00-17:00（16:00停止入园）") == "09:00-17:00 (last entry 16:00)"
    assert t("周二至周日 09:00-17:00 16:30停止检票入馆").startswith(
        "Tuesday–Sunday 09:00-17:00 last entry 16:30"
    )
    assert t("10:00-22:00 21:30停止售票") == "10:00-22:00 last tickets 21:30"
    # 开放家族 / 全年
    assert t("全年全天开放") == "Open year-round, all day"
    assert t("全年开放") == "Open year-round"
    assert t("周一至周五 10:00-17:00开放") == "Monday–Friday 10:00-17:00 open"
    assert t("开放时间:09:00-17:00") == "Opening hours:09:00-17:00"
    # 节假日 / 关闭 / 公示
    assert t("周一关闭(法定节假日除外)") == "Monday Closed(except public holidays)"
    assert t("周一至周日 09:00-17:00，节假日除外") is None  # "除外"无映射→CJK 回落 LLM
    assert t("周一至周日 00:00-24:00；具体开放时间以现场公示为准") == (
        "Monday–Sunday 00:00-24:00; hours subject to on-site notice"
    )
    # 月日日期（保数字）
    assert t("11月至12月 周一至周日 08:00-16:30") == "Nov–Dec Monday–Sunday 08:00-16:30"
    assert t("2026年2月16日闭馆") == "2026 Feb 16 Closed"
    assert t("1月1日-1月3日:10:00-22:00") == "Jan 1-Jan 3:10:00-22:00"
    # 2026-10-30 第二批：今天/每日/夜游/国家法定/点时刻/全天关闭/日期前后
    assert t("今天09:00-17:00开放（16:00停止入园）") == (
        "today 09:00-17:00 open (last entry 16:00)"
    )
    assert t("夜游开放时间为每日17:30-22:00（21:45停止入场）") == (
        "night tour Opening hours daily 17:30-22:00 (last entry 21:45)"
    )
    assert t("周一关闭(国家法定节假日除外)") == (
        "Monday Closed(except national public holidays)"
    )
    assert t("周一 全天关闭") == "Monday Closed all day"
    assert t("5月1日前 08:00-16:30停止入园") == (
        "before May 1 08:00-16:30, last entry 16:30"
    )
    assert t("09:00-18点") == "09:00-18:00"


def test_process_row_template_path_zero_llm():
    """hours 模板可转换 → 零 LLM 调用（省 token 路径）。"""
    adapter = _FakeAdapter({})
    row = _EnRow(name_en="Palace Museum", opening_hours="周一至周日 08:30-17:00")
    stats, writes = _run(row, adapter)
    assert adapter.calls == []
    assert stats["template"] == 1
    merged = {}
    for w in writes:
        merged.update(w)
    assert merged["opening_hours_en"] == "Monday–Sunday 08:30-17:00"


def test_process_row_rejects_overlong_for_varchar_column():
    """译文超 VARCHAR 列限（address_en 200）→ 拒收，不进写库（防掀批）。"""
    long_en = "Long Address Translation " + "x" * 220  # >200 字符
    adapter = _FakeAdapter({"把以下中文译成英文：北京市东城区景山前街4号": long_en})
    row = _EnRow(name_en="Set", address="北京市东城区景山前街4号")
    stats, writes = _run(row, adapter)
    assert writes == []
    assert stats["rejected"] == 1


def test_process_row_write_failure_isolated():
    """单行写库抛异常 → 只计 errors，不掀翻批次。"""
    import app.jobs.backfill_en_columns as mod

    adapter = _FakeAdapter({"把以下中文译成英文：故宫": "The Forbidden City"})
    row = _EnRow(name_zh="故宫")
    stats = {
        "rows_filled": 0,
        "fields_filled": 0,
        "skipped": 0,
        "rejected": 0,
        "rejected_by_reason": {},
        "errors": 0,
        "template": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }

    def boom(session_factory, model, row_id, updates):
        raise RuntimeError("db down")

    old = mod._write_row
    mod._write_row = boom
    try:
        asyncio.run(
            mod._process_row(adapter, None, row, "pois", asyncio.Semaphore(2), stats)
        )
    finally:
        mod._write_row = old
    assert stats["errors"] == 1
    assert stats["rows_filled"] == 0


def test_validate_hours_en_time_drift():
    from app.jobs.backfill_en_columns import validate_hours_en

    # 时刻数字必须保真
    assert (
        validate_hours_en("Mon-Sun 09:00-17:00", source="周一至周日 09:00-17:00")
        is None
    )
    assert (
        validate_hours_en("Mon-Sun 09:00-18:00", source="周一至周日 09:00-17:00")
        == "time_drift"
    )
    assert validate_hours_en("Monday Closed", source="周一闭馆") is None
    # 残句意译：禁中文回退
    assert validate_hours_en("今天开放", source="今天开放") == "no_latin"
    assert (
        validate_hours_en(
            "Open today 09:00-17:00; last entry 16:00",
            source="今天09:00-17:00开放（16:00停止入园）",
        )
        is None
    )
