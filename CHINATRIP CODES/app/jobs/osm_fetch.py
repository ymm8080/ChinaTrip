"""Geofabrik 中国区日增 .osc.gz 下载器（配合 app.jobs.osm_diff 使用）.

Geofabrik 更新目录（china-updates）用零填充序号子目录逐日递增，本 job
抓 index 页全部 .osc.gz 链接，对照水位文件（--state，与 osm_diff 共用
data/osm_state.json 的 last_osc 键）只取未应用过的文件：下载到 --dir
后 stdout 每行输出一个路径供 cmd for /f 消费；无新文件输出 NONE、
退出 0。真正落库仍归 osm_diff（应用成功才写水位，下载失败/中断下次
自动续传或复用已下载文件）。

用法：
    python -m app.jobs.osm_fetch [--dir data/osm] [--state data/osm_state.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

INDEX_URL = "https://download.geofabrik.de/asia/china-updates/"
_UA = "ChinaTrip-POI-library/0.1 (contact: dev@chinatrip.local)"
_OSC_HREF = re.compile(r'href="([^"]+\.osc\.gz)"', re.IGNORECASE)


def list_osc_hrefs(index_html: str) -> list[str]:
    """index 页里全部 .osc.gz 链接（去重、按零填充序号升序）。"""
    return sorted(set(_OSC_HREF.findall(index_html)))


def pending_hrefs(hrefs: list[str], last_name: str | None) -> list[str]:
    """水位之后的待应用文件；水位 None 取最新一个，滑出窗口只追最新。"""
    if not hrefs:
        return []
    names = [Path(h).name for h in hrefs]
    if last_name is not None and last_name in names:
        return list(hrefs[names.index(last_name) + 1 :])
    return [hrefs[-1]]


def last_applied(state_path: Path) -> str | None:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("last_osc")
    return value if isinstance(value, str) else None


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)


def fetch_pending(
    index_html: str, state_path: Path, dest_dir: Path
) -> list[Path]:
    """下载全部待应用 .osc.gz（已存在则复用），返回本地路径列表。"""
    pending = pending_hrefs(list_osc_hrefs(index_html), last_applied(state_path))
    out: list[Path] = []
    for href in pending:
        dest = dest_dir / Path(href).name
        if not dest.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
            _download(urljoin(INDEX_URL, href), dest)
        out.append(dest)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="下载 Geofabrik 中国区未应用的日增 .osc.gz"
    )
    parser.add_argument("--dir", default="data/osm", help="下载目录")
    parser.add_argument(
        "--state", default="data/osm_state.json", help="水位文件（osm_diff 共用）"
    )
    args = parser.parse_args(argv)

    try:
        req = urllib.request.Request(INDEX_URL, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            index_html = resp.read().decode("utf-8", errors="replace")
        downloaded = fetch_pending(index_html, Path(args.state), Path(args.dir))
    except Exception as exc:
        print(json.dumps({"error": str(exc)[:200]}, ensure_ascii=True))
        return 1
    if not downloaded:
        print("NONE")
        return 0
    for path in downloaded:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
