# H5 规划起始页路线表单守门（ops/check_plan_form.js）的 pytest 外壳：
# 随常规测试套件运行。
#
# 2026-11-13 事故回归（用户：起始北京 / 旅游上海 3 天 / 结束上海 → 实际只排 1 天）：
# 中间城市与结束城市同城时，旧版 planRouteForm() 把整行（含用户填的 3 天）丢弃，
# 结束城市默认 1 天顶上，请求 days 塌成 1。守门脚本逐案钉住「同城并天不丢天」，
# 本机没有 node 时 skip，不阻塞其他平台/CI。
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "ops" / "check_plan_form.js"


def test_plan_form_same_city_days_kept():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不可用，跳过 H5 规划表单守门")
    r = subprocess.run(
        [node, str(CHECKER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, (
        "H5 规划表单守门未过：\n" + (r.stdout or "") + (r.stderr or "")
    )
    assert "全部通过" in (r.stdout or "")


def test_city_day_ranges_keeps_single_destination_days():
    """后端口径对照：北京→上海 3 天、city_days={上海:3} → 上海活动窗 (1,3)。"""
    from app.services.agent.plan import _city_day_ranges

    assert _city_day_ranges(["北京", "上海"], 3, {"上海": 3}) == {"上海": (1, 3)}
