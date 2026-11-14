# -*- coding: utf-8 -*-
"""天安门升（降）旗时刻（flag_schedule 设计 2026-11-14，三段式）：

① 模块单点：公告页 URL → 表图 OCR → 落库（只追加批次）+ DESIGN 快照；
② 本地表 year,date,rise_time,lower_time，按日期 + 类别（morning/evening）
   查询；
③ 规划引擎装配期打标 fixed_sessions——天安门广场当日开始时间 = 升旗
   时刻，solver/兜底两路同口径锚定（可破 8:30 日始；用户自钉铁律 19
   优先）。

测试全部离线：OCR 不进测试（parse_grid_cells 吃伪造单元格）；HTTP 用
httpx.MockTransport；查询走 tmp SQLite（种子 CSV 灌入）。
"""

import csv
from datetime import time as _t
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.services import flag_schedule as fs
from app.services.agent.plan import (
    _apply_flag_schedule,
    _fallback_sequence_times,
)
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.solver import insertion_schedule_day, solve_day

# ---------------------------------------------------------------- 脚手架


@pytest.fixture()
def flag_env(tmp_path, monkeypatch):
    """隔离环境：tmp SQLite + 关闭真实快照目录；模块级缓存复位。

    （_flag_cache/_flag_engine 是进程级单例——测试间必须复位，否则
    上一用例的 max(id) 代际会让本用例读到旧库。）"""
    settings = Settings(
        flag_schedule_db_url=f"sqlite:///{tmp_path}/flag_cache.db",
        flag_schedule_snapshot_dir=str(tmp_path / "DESIGN"),
    )
    fs._flag_engine = None
    fs._flag_cache = {}
    fs._flag_cache_generation = None
    yield settings
    fs._flag_engine = None
    fs._flag_cache = {}
    fs._flag_cache_generation = None


def _minutes(v: VisitItem) -> int:
    assert v.start_time is not None
    return v.start_time.hour * 60 + v.start_time.minute


def _visit(item_id, name, *, dur=60, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city="北京",
        day=1,
        duration_minutes=dur,
        category="sight",
    )
    base.update(kw)
    return VisitItem(**base)


# ------------------------------------------------------------ ② 查询路径


def test_seed_lookup_morning_and_evening(flag_env):
    """种子灌入后按日期+类别查询：morning=升旗 / evening=降旗。"""
    assert fs._ensure_seed(settings=flag_env) == 365
    assert fs._ensure_seed(settings=flag_env) == 0  # 幂等：已有年份跳过
    assert fs.get_flag_time("2026-11-14", "morning", settings=flag_env) == _t(6, 58)
    assert fs.get_flag_time("2026-11-14", "evening", settings=flag_env) == _t(17, 0)
    # 中文类别别名
    assert fs.get_flag_time("2026-11-14", "升旗", settings=flag_env) == _t(6, 58)
    assert fs.get_flag_time("2026-11-14", "降旗", settings=flag_env) == _t(17, 0)


def test_lookup_misses_degrade_to_none(flag_env):
    """缺数据/坏类别恒 None（降级契约：规划侧按默认日始排）。"""
    fs._ensure_seed(settings=flag_env)
    assert fs.get_flag_time("2026-02-29", "morning", settings=flag_env) is None
    assert fs.get_flag_time("2025-01-01", "morning", settings=flag_env) is None
    assert fs.get_flag_time("2026-11-14", "noon", settings=flag_env) is None


def test_disabled_flag_schedule_returns_none(tmp_path):
    """开关关闭：查询恒 None，零 DB IO（引擎单例不创建）。"""
    fs._flag_engine = None
    fs._flag_cache = {}
    fs._flag_cache_generation = None
    settings = Settings(
        flag_schedule_enabled=False,
        flag_schedule_db_url=f"sqlite:///{tmp_path}/unused.db",
    )
    assert fs.get_flag_time("2026-11-14", "morning", settings=settings) is None
    assert fs._flag_engine is None


def test_append_only_batches_latest_wins(flag_env):
    """只追加不替换（2026-11-14 用户拍板）：新批次整批 INSERT，读取取
    每 date 最新 fetched_at 批次；旧行留档不删。"""
    fs._ensure_seed(settings=flag_env)
    rows = [
        {"year": 2026, "date": "2026-11-14", "rise_time": "7:00", "lower_time": "17:00"}
    ]
    fs.insert_batch(rows, source="ocr")
    # 读最新批次
    assert fs.get_flag_time("2026-11-14", "morning", settings=flag_env) == _t(7, 0)
    # 其他日期不受新批次影响（批次只含 11-14）
    assert fs.get_flag_time("2026-11-13", "morning", settings=flag_env) == _t(6, 57)
    # 旧行留档：库里 2026-11-14 有两行（seed 批 + ocr 批）
    with fs.Session(fs.get_flag_schedule_engine(flag_env)) as session:
        n = session.execute(
            fs.select(fs.func.count(fs.FlagScheduleRecord.id)).where(
                fs.FlagScheduleRecord.date == "2026-11-14"
            )
        ).scalar()
    assert n == 2


# ------------------------------------------------- ② 解析 + 校验闸门


def _seed_2026_rows():
    path = next(p for p in fs._SEED_CSV_CANDIDATES if Path(p).exists())
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _synth_cells(rows):
    """按真表版式伪造 OCR 单元格 [(x, y, text)]：日列 + 12 月 × 升/降。"""
    num_to_cn = {v: k for k, v in fs._CN_MONTH_NUM.items()}
    cells = []
    # 表头：月/日 + 12 个月名（月名列簇中心 x=100+80*(m-1)，时刻列在其右）
    cells.append((30, 20, "月"))
    cells.append((30, 40, "日"))
    for m in range(1, 13):
        hx = 100 + 80 * (m - 1)
        cells.append((hx, 20, num_to_cn[m]))
        cells.append((hx + 25, 40, "升"))
        cells.append((hx + 55, 40, "降"))
    # 数据行：y=70+20*(d-1)
    by_md = {(int(r["date"][5:7]), int(r["date"][8:10])): r for r in rows}
    for m in range(1, 13):
        for d in range(1, 32):
            r = by_md.get((m, d))
            y = 70 + 20 * (d - 1)
            cells.append((30, y, str(d)))
            if r:
                hx = 100 + 80 * (m - 1)
                cells.append((hx + 25, y, r["rise_time"]))
                cells.append((hx + 55, y, r["lower_time"]))
    return cells


def test_parse_grid_cells_reconstructs_full_year():
    """全 12 月版式还原：伪造单元格 → parse_grid_cells 与种子逐格一致。"""
    rows = _seed_2026_rows()
    parsed = fs.parse_grid_cells(_synth_cells(rows))
    got = fs.validate_rows(parsed, 2026)
    by_date = {r["date"]: r for r in got}
    assert len(got) == 365
    for r in rows:
        g = by_date[r["date"]]
        assert g["rise_time"] == r["rise_time"], r["date"]
        assert g["lower_time"] == r["lower_time"], r["date"]


def test_validate_rows_rejects_missing_day():
    """校验闸门：缺日不落库。"""
    rows = [
        {"month": 1, "day": d, "rise": "7:36", "lower": "17:00"} for d in range(1, 5)
    ]  # 只 4 天
    with pytest.raises(ValueError):
        fs.validate_rows(rows, 2026)


def test_validate_rows_rejects_out_of_range_time():
    """校验闸门：时刻越界（降旗 03:00）不落库。"""
    rows = [
        {"month": 1, "day": d, "rise": "7:36", "lower": "17:00" if d > 1 else "3:00"}
        for d in range(1, 32)
    ]
    with pytest.raises(ValueError):
        fs.validate_rows(rows, 2026)


def test_validate_rows_rejects_drift():
    """校验闸门：相邻天漂移 >3 分钟（OCR 误读形态）不落库。"""
    rows = [
        {"month": 1, "day": d, "rise": "7:36" if d < 10 else "7:50", "lower": "17:00"}
        for d in range(1, 32)
    ]
    with pytest.raises(ValueError):
        fs.validate_rows(rows, 2026)


def test_extract_table_image_url():
    """公告页 → 表图 URL（TRS W0 前缀，相对页面目录）。"""
    html = (
        "<div>2026年天安门广场升（降）国旗时刻表</div>"
        '<img src="./W020260101375936698358.png" />'
    ).encode("utf-8")
    url = fs._extract_table_image_url(
        html,
        "https://tamgw.beijing.gov.cn/sy/sjqsj/202512/t20251222_4356494.html",
    )
    assert url == (
        "https://tamgw.beijing.gov.cn/sy/sjqsj/202512/W020260101375936698358.png"
    )


def test_fetch_and_store_offline(monkeypatch, flag_env, tmp_path):
    """抓取全链（离线）：MockTransport 假页面+假图 → OCR 桩（伪造 parse
    输出）→ 落库 + 快照。校验不过不落库由 validate 用例覆盖。"""
    page = (
        "<html>首都北京天安门广场升降国旗时刻表（2026年）"
        '<img src="./W020260101375936698358.png"/></html>'
    ).encode("utf-8")
    png = b"\x89PNG fake"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".png"):
            return httpx.Response(200, content=png)
        return httpx.Response(200, content=page)

    def fake_http_get(url: str, **kw) -> bytes:
        return httpx.Client(transport=httpx.MockTransport(handler)).get(url).content

    parsed = [
        {
            "month": int(r["date"][5:7]),
            "day": int(r["date"][8:10]),
            "rise": r["rise_time"],
            "lower": r["lower_time"],
        }
        for r in _seed_2026_rows()
    ]
    monkeypatch.setattr(fs, "_http_get", fake_http_get)
    monkeypatch.setattr(fs, "_IMG_CACHE_DIR", tmp_path / "imgcache")
    monkeypatch.setattr(fs, "_ocr_image", lambda path: [])
    monkeypatch.setattr(fs, "parse_grid_cells", lambda cells: parsed)
    summary = fs.fetch_and_store(
        "https://tamgw.beijing.gov.cn/x.html", settings=flag_env
    )
    assert summary["rows"] == 365
    assert fs.get_flag_time("2026-11-14", "morning", settings=flag_env) == _t(6, 58)
    # DESIGN 快照落盘
    import pathlib

    snaps = list(
        pathlib.Path(flag_env.flag_schedule_snapshot_dir).glob(
            "flag_schedule_snapshot_*.csv"
        )
    )
    assert len(snaps) == 1


# --------------------------------------------------- ③ 规划引擎接线


def test_solver_anchor_both_paths():
    """solver 双路（最廉插入/CP）：fixed_sessions 锚定 6:58 恰点，可破
    8:30 日始；同日后续晨点（故宫）8:30 正常跟进（_is_morning_site
    升旗豁免面）。"""
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _visit("tam", "天安门广场", fixed_sessions=[_t(6, 58)]),
            _visit("gg", "故宫博物院", dur=120),
        ],
    )
    for solver in (insertion_schedule_day, solve_day):
        kw = {} if solver is insertion_schedule_day else {"time_budget_seconds": 3.0}
        out = solver(day, poi_hours=[], travel_minutes=None, **kw)
        by = {i.name: i for i in out.items}
        assert _minutes(by["天安门广场"]) == 6 * 60 + 58
        assert _minutes(by["故宫博物院"]) == 8 * 60 + 30


def test_flag_anchor_beats_pinned_form_time():
    """2026-11-14 拍板「数据库旗时最高优先级」：附加信息窗的默认起止
    时间（以 pinned+start_time 落卡，如默认 9:00）被旗时覆盖——天安门
    卡 pinned 也锚升旗时刻；钉位本身保留（卡不挪日）。"""
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _visit(
                "tam",
                "天安门广场",
                pinned=True,
                start_time=_t(9, 0),
                fixed_sessions=[_t(6, 58)],
            ),
        ],
    )
    out = insertion_schedule_day(day, poi_hours=[], travel_minutes=None)
    assert _minutes(out.items[0]) == 6 * 60 + 58


def test_fallback_anchor_via_session_channel():
    """兜底顺序排：fixed_sessions 走场次点通道，旗时点落位 + 旗后上午
    继续排点（游标不跳 12 点——升旗豁免面同 solver）。"""
    plan = ItineraryPlan(
        itinerary_id="it-flag",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    _visit("tam", "天安门广场", fixed_sessions=[_t(6, 58)]),
                    _visit("gg", "故宫博物院", dur=120),
                ],
            )
        ],
        start_date="2026-11-14",
    )
    _fallback_sequence_times(plan)
    by = {i.name: i for i in plan.days[0].items}
    assert _minutes(by["天安门广场"]) == 6 * 60 + 58
    assert _minutes(by["故宫博物院"]) == 8 * 60 + 30


def test_apply_flag_schedule_stamps_from_lookup(monkeypatch, flag_env):
    """装配期打标：天安门广场+北京+start_date → 查表落标 fixed_sessions。"""
    monkeypatch.setattr(
        fs,
        "get_flag_time",
        lambda date_iso, category, **kw: (
            _t(6, 58) if (date_iso, category) == ("2026-11-14", "morning") else None
        ),
    )
    plan = ItineraryPlan(
        itinerary_id="it-flag",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    _visit("tam", "天安门广场"),
                    _visit("gg", "故宫博物院"),
                ],
            )
        ],
        start_date="2026-11-14",
    )
    _apply_flag_schedule(plan)
    assert plan.days[0].items[0].fixed_sessions == [_t(6, 58)]
    assert plan.days[0].items[1].fixed_sessions is None  # 非天安门不打标


def test_apply_flag_schedule_skip_cases(monkeypatch):
    """跳过面：无 start_date / 非广场名（纪念堂）/ 用户自钉 / 非北京。"""
    monkeypatch.setattr(
        fs,
        "get_flag_time",
        lambda date_iso, category, **kw: _t(6, 58),
    )

    def _plan(start_date, items, cities=("北京",)):
        return ItineraryPlan(
            itinerary_id="it-flag",
            cities=list(cities),
            days=[DayPlan(day=1, base_city=cities[0], items=items)],
            start_date=start_date,
        )

    # 无 start_date → 不打标
    p = _plan(None, [_visit("tam", "天安门广场")])
    _apply_flag_schedule(p)
    assert p.days[0].items[0].fixed_sessions is None
    # 非广场（纪念堂）→ 不打标
    p = _plan("2026-11-14", [_visit("jnt", "毛主席纪念堂")])
    _apply_flag_schedule(p)
    assert p.days[0].items[0].fixed_sessions is None
    # 用户自钉（附加信息窗默认时间）→ 仍打标（2026-11-14 最高优先级拍板）
    p = _plan(
        "2026-11-14", [_visit("tam", "天安门广场", pinned=True, start_time=_t(9, 0))]
    )
    _apply_flag_schedule(p)
    assert p.days[0].items[0].fixed_sessions == [_t(6, 58)]
    # 非北京 → 不打标
    p = _plan(
        "2026-11-14", [_visit("tam", "天安门广场", city="上海")], cities=("上海",)
    )
    _apply_flag_schedule(p)
    assert p.days[0].items[0].fixed_sessions is None


def test_stamp_overwrites_pinned_form_time_directly():
    """2026-11-14 三修：附加信息窗默认起止时间（pinned+start_time=8:30）
    被旗时直接改写——兜底/行程中心编辑路径把已有时刻当固定锚，只打
    fixed_sessions 不改写的话 8:30 会固化成当日窗（UAT 实况：
    fixed=07:10 已打标、start 仍 8:30）。"""
    p = ItineraryPlan(
        itinerary_id="it-flag-overwrite",
        cities=["北京"],
        days=[
            DayPlan(
                day=1,
                base_city="北京",
                items=[
                    _visit(
                        "tam",
                        "天安门广场",
                        pinned=True,
                        start_time=_t(8, 30),
                        fixed_sessions=None,
                    ),
                ],
            )
        ],
        start_date="2026-11-25",  # 升旗 7:10
    )
    _apply_flag_schedule(p)
    item = p.days[0].items[0]
    assert item.fixed_sessions == [_t(7, 10)]
    assert item.start_time == _t(7, 10)  # 直接改写，不等 solver
    assert item.end_time == _t(8, 10)  # 默认 60 分钟
    assert item.pinned is True  # 钉位保留（卡不挪日）
