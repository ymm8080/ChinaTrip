# H5 酒店 → 预订页守门（ops/check_hotel_book.js）的 pytest 外壳：随常规测试套件运行。
#
# 2026-11-26 用户令「点酒店 → 预订页，页上有酒店名 + Trip/Booking/Agoda 三个按钮」：
# 守门钉住两家按钮吃「选中酒店」而不是只吃城市，并检查接线（面板按钮 / 酒店名链接 /
# 点击委托里的 hotelGotoBook）。本机没有 node 时 skip，不阻塞其他平台/CI。
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "ops" / "check_hotel_book.js"


def test_hotel_click_goes_to_reservation_page():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不可用，跳过 H5 酒店预订守门")
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
        "H5 酒店→预订页守门未过：\n" + (r.stdout or "") + (r.stderr or "")
    )
    assert "全部通过" in (r.stdout or "")
