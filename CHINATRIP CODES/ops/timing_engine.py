"""自研定时引擎（timing engine，2026-10-25 用户点名自建）。

定位：LLM 续跑层（ZCode 每 2 分钟巡检）之下的**确定性执行层**——
不依赖外部调度器的通用作业引擎：到期计算 / 失败退避 / 水位持久化 /
单次模式（--once，供 schtasks/计划任务每 2 分钟拉起）与常驻模式
（--loop）。零第三方依赖（纯 stdlib），进程被杀水位不丢（重启续跑）。

用法：
    python ops/timing_engine.py --list              # 列作业与下次到期
    python ops/timing_engine.py --once              # 跑所有到期作业一次退出
    python ops/timing_engine.py --once --job heartbeat
    python ops/timing_engine.py --loop              # 常驻（sleep 粒度 5s）
    python ops/timing_engine.py --run-now progress_probe   # 忽略到期立刻跑

作业注册：下方 JOBS dict（name → JobSpec）。内置三件：
    heartbeat        每 5 分钟写 devlogs/timing_heartbeat.log（引擎活着）
    progress_probe   每 2 分钟读 PROGRESS 文档待办计数 →
                     data/dev_pending.flag（有待办=True）——LLM 巡检层
                     与外部观测都读这个标志
    tests_smoke      每 60 分钟快测（默认禁用 enabled=False，防止
                     与开发进程抢 .pyc/DB；要开手动置 True）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # CHINATRIP CODES/
LOG_DIR = ROOT / "devlogs"
STATE_FILE = ROOT / "data" / "timing_state.json"
PROGRESS_FILE = ROOT.parent / "DESIGN" / "planning_engine_upgrade_PROGRESS.md"

#: 退避上限（秒）：失败后 interval×2^n 封顶
BACKOFF_MAX_SECONDS = 1800
#: 单作业超时（秒）
JOB_TIMEOUT_SECONDS = 900


@dataclass
class JobSpec:
    name: str
    interval_seconds: int
    command: list[str]  # 相对 ROOT 的参数（python 用 sys.executable 注入）
    enabled: bool = True
    describe: str = ""


@dataclass
class JobState:
    next_due: float  # time.monotonic 不落盘；落盘用 wall epoch
    last_run: float | None = None
    last_ok: bool | None = None
    failures: int = 0


def _builtin_jobs() -> dict[str, JobSpec]:
    py = sys.executable
    return {
        "heartbeat": JobSpec(
            name="heartbeat",
            interval_seconds=300,
            command=[
                py,
                "-c",
                "from datetime import datetime;"
                "open(r'devlogs/timing_heartbeat.log','a').write("
                "datetime.now().isoformat()+chr(10))",
            ],
            describe="每 5 分钟心跳一行（引擎活性）",
        ),
        "progress_probe": JobSpec(
            name="progress_probe",
            interval_seconds=120,
            command=[py, str(Path(__file__).parent / "timing_probe.py")],
            describe="每 2 分钟探测 PROGRESS 待办 → data/dev_pending.flag",
        ),
        "tests_smoke": JobSpec(
            name="tests_smoke",
            interval_seconds=3600,
            command=[py, "-m", "pytest", "tests/test_health.py", "-q"],
            enabled=False,  # 默认关：防与开发进程抢资源
            describe="每小时健康冒烟（默认禁用）",
        ),
    }


# --- 纯函数（测试吃这些） -----------------------------------------------------


def next_due_after(
    now: float, interval: int, failures: int, *, backoff_max: int = BACKOFF_MAX_SECONDS
) -> float:
    """失败退避：interval × 2^failures 封顶 backoff_max；成功即 interval。"""
    if failures <= 0:
        return now + interval
    delay = min(interval * (2**failures), backoff_max)
    return now + delay


def load_state(path: Path) -> dict[str, JobState]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, JobState] = {}
    for name, st in raw.items():
        try:
            out[name] = JobState(
                next_due=float(st["next_due"]),
                last_run=st.get("last_run"),
                last_ok=st.get("last_ok"),
                failures=int(st.get("failures") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save_state(path: Path, state: dict[str, JobState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        name: {
            "next_due": st.next_due,
            "last_run": st.last_run,
            "last_ok": st.last_ok,
            "failures": st.failures,
        }
        for name, st in state.items()
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # 原子写：杀进程不留半截状态


def due_jobs(
    jobs: dict[str, JobSpec], state: dict[str, JobState], now: float
) -> list[str]:
    """到期作业名（无状态的首次注册立即到期）。"""
    out = []
    for name, spec in jobs.items():
        if not spec.enabled:
            continue
        st = state.get(name)
        if st is None or now >= st.next_due:
            out.append(name)
    return sorted(out)


# --- 执行 -------------------------------------------------------------------


def run_job(spec: JobSpec, st: JobState, *, now: float, log) -> JobState:
    log(f"[{spec.name}] start: {' '.join(spec.command[1:3])}…")
    ok = True
    try:
        proc = subprocess.run(
            spec.command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=JOB_TIMEOUT_SECONDS,
        )
        ok = proc.returncode == 0
        if not ok:
            log(
                f"[{spec.name}] FAIL rc={proc.returncode} stderr={proc.stderr[-300:]!r}"
            )
    except subprocess.TimeoutExpired:
        ok = False
        log(f"[{spec.name}] TIMEOUT >{JOB_TIMEOUT_SECONDS}s")
    except Exception as exc:  # 引擎自身不因单作业崩
        ok = False
        log(f"[{spec.name}] ERROR {exc!r}")
    st.failures = 0 if ok else st.failures + 1
    st.last_run = now
    st.last_ok = ok
    st.next_due = next_due_after(now, spec.interval_seconds, st.failures)
    log(
        f"[{spec.name}] {'ok' if ok else 'fail'} "
        f"failures={st.failures} next_due=+{int(st.next_due - now)}s"
    )
    return st


def _log_to_file(line: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "timing_engine.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自研定时引擎（确定性执行层）")
    parser.add_argument("--list", action="store_true", help="列作业与到期")
    parser.add_argument("--once", action="store_true", help="跑到期作业一次退出")
    parser.add_argument("--loop", action="store_true", help="常驻模式")
    parser.add_argument("--job", help="只跑指定作业")
    parser.add_argument("--run-now", help="忽略到期立刻跑指定作业一次")
    args = parser.parse_args(argv)

    jobs = _builtin_jobs()
    state = load_state(STATE_FILE)
    log = _log_to_file

    if args.run_now:
        spec = jobs.get(args.run_now)
        if spec is None:
            print(f"unknown job: {args.run_now}")
            return 2
        st = state.get(spec.name) or JobState(next_due=0)
        state[spec.name] = run_job(spec, st, now=time.time(), log=log)
        save_state(STATE_FILE, state)
        return 0 if state[spec.name].last_ok else 1

    if args.list:
        now = time.time()
        for name, spec in jobs.items():
            st = state.get(name)
            due = "n/a" if st is None else f"+{max(0, int(st.next_due - now))}s"
            print(
                f"{name:16} interval={spec.interval_seconds:>5}s "
                f"enabled={spec.enabled} next_due={due} {spec.describe}"
            )
        return 0

    def sweep() -> int:
        now = time.time()
        ran = 0
        for name in due_jobs(jobs, state, now):
            if args.job and name != args.job:
                continue
            spec = jobs[name]
            st = state.get(name) or JobState(next_due=now)
            state[name] = run_job(spec, st, now=now, log=log)
            ran += 1
        if ran:
            save_state(STATE_FILE, state)
        return ran

    if args.once:
        sweep()
        return 0
    if args.loop:
        print("timing engine loop mode (Ctrl+C 退出)…")
        try:
            while True:
                sweep()
                time.sleep(5)
        except KeyboardInterrupt:
            save_state(STATE_FILE, state)
            return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
