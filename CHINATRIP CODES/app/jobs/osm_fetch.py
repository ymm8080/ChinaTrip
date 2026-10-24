"""OSM planet 小时复制增量下载器（配合 app.jobs.osm_diff 使用）.

源实测（2026-10-24）：download.geofabrik.de 本机 TCP 死（连 VPN 也超时），
planet.openstreetmap.org 可达（需 VPN）。planet 的 replication/hour 没有
索引页，序号按固定纪元（2012-09-12T08:15:45Z）每小时 +1，只能探测：
先按时间猜一个序号，向上探测穿过空洞，最后一个能拿到 .state.txt 的即最新。

水位复用 osm_diff 的 data/osm_state.json last_osc 键（值形如
planet_hour_000123717.osc.gz，应用成功才写）。下载到 --dir 后 stdout
每行输出一个路径供 poi_daily.cmd 的 for /f 消费；无新文件输出 NONE、
退出 0。真正落库归 osm_diff。追补上限 MAX_CATCHUP 个小时文件，防止
长期停跑后第一次运行变成无界批量下载。

用法：
    python -m app.jobs.osm_fetch [--dir data/osm] [--state data/osm_state.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://planet.openstreetmap.org/replication/hour/"
_UA = "ChinaTrip-POI-library/0.1 (contact: dev@chinatrip.local)"
_EPOCH = datetime(2012, 9, 12, 8, 15, 45, tzinfo=timezone.utc)
_LAST_OSC = re.compile(r"^planet_hour_(\d{9})\.osc\.gz$")
MAX_CATCHUP = 48  # 最多追补 48 个小时增量（约 86MB）


def serial_path(serial: int) -> str:
    """序号 -> 三段相对路径（123717 -> 000/123/717）。"""
    s = f"{serial:09d}"
    return f"{s[:3]}/{s[3:6]}/{s[6:]}"


def fetch_serial_state(serial: int, timeout: int = 30) -> bool:
    """探测某序号的 .state.txt 是否存在（存在即该小时已产出）。"""
    url = f"{BASE_URL}{serial_path(serial)}.state.txt"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True
    except Exception:
        return False


def probe_latest_serial(now: datetime | None = None) -> int | None:
    """按时间猜序号，向上穿洞再向下兜时钟偏斜 -> 最新已产出序号；全失败 None。"""
    t = now or datetime.now(timezone.utc)
    serial = int((t - _EPOCH).total_seconds() // 3600) + 1
    for _ in range(10):
        if fetch_serial_state(serial + 1):
            serial += 1
        else:
            break
    for _ in range(5):  # 猜测超过实际最新（本机时钟偏快）时向下回退
        if fetch_serial_state(serial):
            return serial
        serial -= 1
    return None


def last_serial(state_path: Path) -> int | None:
    """从共用水位文件读 last_osc 里的 planet 序号；无/非 planet 命名 -> None。"""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("last_osc")
    if not isinstance(value, str):
        return None
    m = _LAST_OSC.match(value)
    return int(m.group(1)) if m else None


def pending_serials(last: int | None, latest: int) -> list[int]:
    """水位之后的序号列表；水位 None 只取最新一个（与旧 Geofabrik 行为一致）。"""
    if last is None:
        return [latest]
    start = max(last + 1, latest - MAX_CATCHUP + 1)
    return list(range(start, latest + 1))


def _download(serial: int, dest_dir: Path) -> Path:
    url = f"{BASE_URL}{serial_path(serial)}.osc.gz"
    dest = dest_dir / f"planet_hour_{serial:09d}.osc.gz"
    if not dest.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as fh:
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="下载 OSM planet 未应用的小时增量 .osc.gz"
    )
    parser.add_argument("--dir", default="data/osm", help="下载目录")
    parser.add_argument(
        "--state", default="data/osm_state.json", help="水位文件（osm_diff 共用）"
    )
    args = parser.parse_args(argv)

    try:
        latest = probe_latest_serial()
        if latest is None:
            raise RuntimeError("planet replication unreachable (no state file)")
        pending = pending_serials(last_serial(Path(args.state)), latest)
        downloaded = [_download(s, Path(args.dir)) for s in pending]
    except Exception as exc:
        # 错误只进 stderr——stdout 是 poi_daily.cmd for /f 的文件清单通道，
        # 混入错误文本会被当路径传给 osm_diff --osc（2026-10-24 实录）
        print(json.dumps({"error": str(exc)[:200]}, ensure_ascii=True), file=sys.stderr)
        return 1
    if not downloaded:
        print("NONE")
        return 0
    for path in downloaded:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
