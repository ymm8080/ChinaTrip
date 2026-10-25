# H5 静态守门（ops/check_h5_static.js）的 pytest 外壳：随常规测试套件运行。
# 检查内容见该脚本头部注释：
#   A 内联脚本语法门 + B i18n 词典覆盖门（tf/callT 动态 key 仅查 en）
#   + C 残留门（index.html 脚本块内中文必须包在 tf()/callT() zh 兜底参里，
#   EN 迁移未完成的文案会被拦下——迁完即绿）。
# 本机没有 node 时 skip，不阻塞其他平台/CI。
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "ops" / "check_h5_static.js"


def test_h5_static_gate():
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node 不可用，跳过 H5 静态守门")
    r = subprocess.run(
        [node, str(CHECKER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, (
        "H5 静态守门未过：\n" + (r.stdout or "") + (r.stderr or "")
    )
    assert "全部通过" in (r.stdout or "")
