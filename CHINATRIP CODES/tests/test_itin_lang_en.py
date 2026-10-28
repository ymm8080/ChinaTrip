"""P3 itinerary bilingual: pipeline/rules/visa messages follow the lang contextvar.

Every producer keeps zh byte-identical by default; with set_lang("en") the
same call returns EN. Each test resets to zh afterwards (contextvar leak).
"""

from datetime import time

import pytest

from app.services.itinerary.models import (
    DayPlan,
    DiffOp,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.pipeline import (
    PipelineError,
    apply_diffs,
    summarize_changes,
)
from app.services.itinerary.rules import validate_plan
from app.services.itinerary.visa_check import check_240h_transit
from app.services.lang_ctx import set_lang


@pytest.fixture(autouse=True)
def _reset_lang():
    yield
    set_lang("zh")


def _one_visit_plan() -> ItineraryPlan:
    v = VisitItem(item_id="v1", name="外滩", city="上海", day=1)
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[v])],
    )


def _overlap_plan() -> ItineraryPlan:
    a = VisitItem(
        item_id="a",
        name="外滩",
        city="上海",
        day=1,
        start_time=time(9, 0),
        end_time=time(11, 0),
    )
    b = VisitItem(
        item_id="b",
        name="豫园",
        city="上海",
        day=1,
        start_time=time(10, 0),
        end_time=time(12, 0),
    )
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[a, b])],
    )


def test_pipeline_error_message_bilingual():
    diffs = [DiffOp(op="move", item_id="v1")]  # move without new_day
    set_lang("en")
    with pytest.raises(PipelineError) as ei:
        apply_diffs(_one_visit_plan(), diffs)
    assert ei.value.args[0] == "move op is missing new_day"
    set_lang("zh")
    with pytest.raises(PipelineError) as ei:
        apply_diffs(_one_visit_plan(), diffs)
    assert ei.value.args[0] == "move op 缺少 new_day"


def test_change_summary_line_bilingual():
    item = VisitItem(item_id="n1", name="外滩", city="上海", day=1)
    diffs = [DiffOp(op="add", item=item)]
    set_lang("en")
    assert summarize_changes(diffs).change_summary == ["Day 1: added 外滩"]
    set_lang("zh")
    assert summarize_changes(diffs).change_summary == ["第1天 新增 外滩"]


def test_rule_violation_message_bilingual():
    set_lang("en")
    report = validate_plan(_overlap_plan(), poi_hours=[])
    msgs = [v.message for v in report.violations if v.rule_id == 1]
    assert msgs == [
        "Day 1: 外滩(09:00-11:00) and 豫园(10:00-12:00) time ranges overlap"
    ]
    set_lang("zh")
    report = validate_plan(_overlap_plan(), poi_hours=[])
    msgs = [v.message for v in report.violations if v.rule_id == 1]
    assert msgs == ["第1天 外滩(09:00-11:00) 与 豫园(10:00-12:00) 时间区间重叠"]


def test_visa_message_bilingual():
    kwargs = {
        "entry_date": "2026-11-01",
        "exit_date": "2026-11-02",
        "entry_port": "上海浦东",
        "exit_port": "上海浦东",
    }
    set_lang("en")
    res = check_240h_transit(["兰州"], **kwargs)
    assert res.status == "fail"
    assert (
        "The following cities are outside the provinces allowed by the "
        "240h visa-free transit policy: 兰州 (甘肃)" in res.messages
    )
    assert res.messages[-1] == "Final decision rests with border inspection on site"
    set_lang("zh")
    res = check_240h_transit(["兰州"], **kwargs)
    assert "以下城市不在 240h 免签允许省域：兰州（甘肃）" in res.messages
    assert res.messages[-1] == "最终以边检现场认定为准"


def test_visa_port_message_bilingual():
    set_lang("en")
    res = check_240h_transit(["上海"], entry_port="罗湖", exit_port="上海浦东")
    assert (
        'Entry port "罗湖" is not on the list (the list is a 2026-10 verified '
        "snapshot; official sources prevail)" in res.messages
    )
    set_lang("zh")
    res = check_240h_transit(["上海"], entry_port="罗湖", exit_port="上海浦东")
    assert "入境口岸「罗湖」不在名单（名录为 2026-10 校订快照，请以官方为准）" in (
        res.messages
    )
