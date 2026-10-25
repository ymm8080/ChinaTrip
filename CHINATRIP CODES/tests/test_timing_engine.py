"""自研定时引擎测试（ops/timing_engine.py + timing_probe.py 纯函数层）。"""

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"ops_{name}", _ROOT / "ops" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # dataclass 装饰器要求模块已入 sys.modules，否则 __dict__ 崩
    sys.modules[f"ops_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


te = _load("timing_engine")
probe = _load("timing_probe")


# --- 退避 / 到期 ------------------------------------------------------------


def test_next_due_success_is_plain_interval():
    assert te.next_due_after(100.0, 120, 0) == 220.0
    assert te.next_due_after(100.0, 120, -1) == 220.0  # 成功路径


def test_next_due_backoff_doubles_and_caps():
    assert te.next_due_after(100.0, 120, 1) == 340.0  # ×2
    assert te.next_due_after(100.0, 120, 3) == 100.0 + 960  # ×8
    # 封顶：interval×2^n 超过 1800 → 1800
    assert te.next_due_after(100.0, 120, 10) == 100.0 + te.BACKOFF_MAX_SECONDS


def test_due_jobs_first_run_and_reschedule():
    jobs = {
        "a": te.JobSpec(name="a", interval_seconds=60, command=[]),
        "b": te.JobSpec(name="b", interval_seconds=60, command=[], enabled=False),
    }
    state: dict = {}
    assert te.due_jobs(jobs, state, now=0) == ["a"]  # 无状态首跑立即到期
    state["a"] = te.JobState(next_due=100.0)
    assert te.due_jobs(jobs, state, now=99) == []
    assert te.due_jobs(jobs, state, now=100) == ["a"]


# --- 水位持久化 -------------------------------------------------------------


def test_state_roundtrip_atomic(tmp_path):
    path = tmp_path / "data" / "state.json"
    te.save_state(path, {"x": te.JobState(next_due=5.0, last_run=1.0, failures=2)})
    loaded = te.load_state(path)
    assert loaded["x"].next_due == 5.0
    assert loaded["x"].failures == 2
    # 坏文件静默清零（不拖垮引擎）
    path.write_text("{broken", encoding="utf-8")
    assert te.load_state(path) == {}


# --- probe 计数 -------------------------------------------------------------


def test_count_pending_skips_done_and_blocked():
    text = """
- [x] 已完成项
- [ ] 待办 A
- [ ] 待办 B（blocked：docker 未启动）
- [ ] 待办 C
普通行
"""
    assert probe.count_pending(text) == 2  # blocked 不计


def test_probe_writes_flag(tmp_path, monkeypatch):
    flag = tmp_path / "dev_pending.flag"
    monkeypatch.setattr(probe, "PROGRESS", tmp_path / "P.md")
    monkeypatch.setattr(probe, "FLAG", flag)
    (tmp_path / "P.md").write_text("- [ ] 待办 A\n- [x] done\n", encoding="utf-8")
    assert probe.main() == 0
    payload = json.loads(flag.read_text(encoding="utf-8"))
    assert payload["has_pending"] is True
    assert payload["pending"] == 1
    assert payload["sample"] == ["待办 A"]
