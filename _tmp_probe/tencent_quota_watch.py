# -*- coding: utf-8 -*-
"""腾讯 key 日配额守窗探针（2026-11-12，任务3 补证部署）。

背景：detail 图字段验证被 status 121 全阻。证据显示日配额重置不在 0 点
（00:20 即已 121，且 5 QPS 限频下 20 分钟烧不尽 1 万），而重置后新鲜窗口
几分钟内即被 H5 兜底流量抽干——人守必错过。

策略：每 60s 发 1 次 /ws/place/v1/search 最小请求（121 拒绝不计费）。
一旦 status==0（窗口开）：立即补发 detail，扫描图字段键，结果落盘
TENCENT_DETAIL_RESULT.md，进程退出。121/120 以外状态也记录。

上限：36h 硬超时 / 首个成功即停。日志 append 到 tencent_quota_watch.log。
绝不打印 key。运行：python -I _tmp_probe/tencent_quota_watch.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.path.insert(0, r"D:\CHINATRIP\_tmp_probe")

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from probe_place_photos import scan, truncate_url, url_samples  # noqa: E402

OUT_DIR = Path(r"D:\CHINATRIP\_tmp_probe")
LOG = OUT_DIR / "tencent_quota_watch.log"
RESULT = OUT_DIR / "TENCENT_DETAIL_RESULT.md"
INTERVAL = 60.0
HARD_CAP_H = 36.0
PROBE_KW = ("keyword", "楼外楼")
BOUNDARY = "region(杭州,0)"


def now() -> str:
    return dt.datetime.now().strftime("%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


async def get_json(client: httpx.AsyncClient, url: str, params: dict):
    try:
        r = await client.get(url, params=params, timeout=15.0)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        log(f"network error: {type(exc).__name__}")
        return None, None


async def main() -> int:
    s = get_settings()
    key = s.tencent_map_key
    if not key:
        log("FATAL: tencent_map_key not configured")
        return 1
    base = "https://apis.map.qq.com"
    started = dt.datetime.now()
    checks = 0
    log(f"watch start (interval={INTERVAL:.0f}s, cap={HARD_CAP_H:.0f}h)")

    async with httpx.AsyncClient() as client:
        while (dt.datetime.now() - started).total_seconds() < HARD_CAP_H * 3600:
            checks += 1
            st, data = await get_json(client, f"{base}/ws/place/v1/search", {
                "keyword": PROBE_KW[1], "boundary": BOUNDARY,
                "page_size": "1", "page_index": "1", "key": key,
            })
            biz = data.get("status") if isinstance(data, dict) else None
            msg = (data or {}).get("message", "") if isinstance(data, dict) else ""
            if biz == 0:
                log(f"*** WINDOW OPEN after {checks} checks *** — firing full probe")
                await fire_full_probe(client, base, key, data)
                return 0
            if checks % 10 == 1 or biz not in (121, 120):
                log(f"check#{checks}: status={biz} {msg}")
            await asyncio.sleep(INTERVAL)
    log(f"hard cap {HARD_CAP_H:.0f}h reached without window; giving up")
    return 2


async def fire_full_probe(client, base, key, search_data) -> None:
    """窗口开：取 id → detail → 扫图字段 → 落盘。"""
    items = (search_data or {}).get("data") or []
    poi_id = items[0].get("id") if items and isinstance(items[0], dict) else None
    lines = [
        "# 腾讯 /ws/place/v1/detail 图字段验证（守窗自动捕获）",
        "",
        f"- 捕获时间：{now()}",
        f"- search status: 0（配额新鲜窗口）",
        f"- search 首条: title={items[0].get('title')!r}" if items else "- search: no items",
    ]
    hits_all: list = []
    if poi_id:
        st, data = await get_json(client, f"{base}/ws/place/v1/detail",
                                  {"id": poi_id, "key": key})
        lines.append(f"- detail HTTP: {st}")
        if isinstance(data, dict):
            biz = {k: data.get(k) for k in ("status", "message") if k in data}
            lines.append(f"- detail biz: {json.dumps(biz, ensure_ascii=False)}")
            hits_all = scan(data)
            lines.append(f"- 图字段键命中数: {len(hits_all)}")
            for p, sample in hits_all[:20]:
                lines.append(f"  - `{p}` = {sample!r}")
            urls = url_samples(data)
            if urls:
                lines.append("- URL 形字段样例（截断）:")
                for p, u in urls[:8]:
                    lines.append(f"  - `{p}` = {u!r}")
            url_hits = [(p, s) for p, s in hits_all
                        if isinstance(s, str) and s.startswith(("http", "apis.", "maps."))]
            verdict = ("**证实：detail 携带图 URL 字段**（见上键路径）" if url_hits
                       else "**证伪：detail 响应无图 URL 字段**（仅有非 URL 类 photo/image 键或全无）")
            lines += ["", f"- 判定：{verdict}"]
        else:
            lines.append("- detail: non-JSON body")
    else:
        lines.append("- 未取得 poi id，detail 未发")
    RESULT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"result written -> {RESULT.name}; hits={len(hits_all)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
