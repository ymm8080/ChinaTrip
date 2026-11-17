"""探针：百度/腾讯 place detail 响应是否携带图片字段（photos/image 等）。

只打印字段名与命中情况；URL 截断到 域名+路径 前 60 字符；绝不打印 key。
每家最多 2 次调用，串行；单次超时 15s，失败重试不超过 1 次。
"""

import asyncio
import json
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")

import os

os.chdir(r"D:\CHINATRIP\CHINATRIP CODES")

import httpx

from app.config import get_settings

TIMEOUT = 15.0
KEY_RE = re.compile(r"photo|image|album|img", re.IGNORECASE)
URL_RE = re.compile(r"^https?://")


def truncate_url(value: str) -> str:
    """域名+路径 截前 60 字符（去 scheme、去 query）。"""
    try:
        parts = urlsplit(value)
        core = parts.netloc + parts.path
    except ValueError:
        core = value
    return core[:60]


def scan(obj, path="$"):
    """递归扫所有键名，返回 [(键路径, 样例值), ...]，键名含 photo/image/album/img。"""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}"
            if KEY_RE.search(str(k)):
                sample = None
                if isinstance(v, str) and URL_RE.match(v):
                    sample = truncate_url(v)
                elif isinstance(v, str):
                    sample = f"<str len={len(v)}>"
                elif isinstance(v, (int, float, bool)) or v is None:
                    sample = v
                elif isinstance(v, list):
                    sample = f"<list len={len(v)}>"
                elif isinstance(v, dict):
                    sample = f"<dict keys={list(v.keys())[:8]}>"
                hits.append((here, sample))
            hits.extend(scan(v, here))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:5]):  # 列表只扫前 5 个元素，防爆炸
            hits.extend(scan(item, f"{path}[{i}]"))
    return hits


def url_samples(obj, path="$", out=None, limit=6):
    """顺带收集任何形如 http(s) URL 的字符串样例（截断），供报告参考。"""
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and URL_RE.match(v):
                out.append((f"{path}.{k}", truncate_url(v)))
            else:
                url_samples(v, f"{path}.{k}", out, limit)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:5]):
            url_samples(item, f"{path}[{i}]", out, limit)
    return out


async def fetch(client, url, params, label):
    """单次 15s 超时，失败重试不超过 1 次；返回 (http_status, json_dict|None, err)。"""
    for attempt in (1, 2):
        try:
            r = await client.get(url, params=params, timeout=TIMEOUT)
            data = None
            try:
                data = r.json()
            except ValueError:
                pass
            return r.status_code, data, None
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            err = f"{type(exc).__name__}: {exc}"[:200]
            if attempt == 2:
                return None, None, err
            print(f"  [retry] {label} attempt 1 failed: {err}")
    return None, None, "unreachable"


def report_block(title, status, data, err, uid_field=None, uid_value=None):
    print(f"\n===== {title} =====")
    if err:
        print(f"HTTP: N/A  ERROR: {err}")
        return
    print(f"HTTP: {status}")
    if not isinstance(data, dict):
        print("BODY: non-JSON / non-dict")
        return
    # 业务状态码（status/code/message 均不含敏感信息，可打印）
    biz = {k: data.get(k) for k in ("status", "code", "message") if k in data}
    print(f"biz status/message: {json.dumps(biz, ensure_ascii=False)[:200]}")
    hits = scan(data)
    if hits:
        print(f"PHOTO/IMAGE-ISH KEY HITS: {len(hits)}")
        for p, s in hits[:20]:
            print(f"  {p} = {s!r}")
    else:
        print("PHOTO/IMAGE-ISH KEY HITS: 0")
    urls = url_samples(data)
    if urls:
        print("URL-like samples (first 6, truncated):")
        for p, s in urls[:6]:
            print(f"  {p} = {s!r}")
    if uid_field:
        print(f"{uid_field}: {uid_value}")


async def main():
    s = get_settings()
    baidu_ak = s.baidu_ak
    tencent_key = s.tencent_map_key
    print(f"baidu_ak loaded: {bool(baidu_ak)} (len={len(baidu_ak)})")
    print(f"tencent_map_key loaded: {bool(tencent_key)} (len={len(tencent_key)})")

    baidu_uid = tencent_id = None
    baidu_search_data = None
    tencent_search_data = None

    async with httpx.AsyncClient() as client:
        # ---------- 百度 ----------
        if baidu_ak:
            # 第 1 次：search（顺带探 scope=2 search 的 detail_info 是否直接带图）
            params = {
                "ak": baidu_ak,
                "output": "json",
                "scope": "2",
                "query": "楼外楼",
                "region": "杭州",
                "city_limit": "true",
                "page_size": "3",
                "page_num": "0",
            }
            st, data, err = await fetch(
                client, "https://api.map.baidu.com/place/v2/search", params,
                "baidu search",
            )
            baidu_search_data = data
            report_block("BAIDU place/v2/search scope=2 (query=楼外楼 region=杭州)", st, data, err)
            if isinstance(data, dict):
                results = data.get("results")
                if isinstance(results, list) and results and isinstance(results[0], dict):
                    baidu_uid = results[0].get("uid")
                    print(f"first result: name={results[0].get('name')!r} uid={baidu_uid}")
            if baidu_uid:
                # 第 2 次：detail
                dparams = {
                    "ak": baidu_ak,
                    "output": "json",
                    "scope": "2",
                    "uid": baidu_uid,
                }
                st2, ddata, err2 = await fetch(
                    client, "https://api.map.baidu.com/place/v2/detail", dparams,
                    "baidu detail",
                )
                report_block(f"BAIDU place/v2/detail scope=2 uid={baidu_uid}", st2, ddata, err2)
        else:
            print("\nBAIDU: no baidu_ak configured, skipped")

        # ---------- 腾讯 ----------
        if tencent_key:
            # 第 1 次：search
            params = {
                "keyword": "楼外楼",
                "boundary": "region(杭州,0)",
                "page_size": "3",
                "page_index": "1",
                "key": tencent_key,
            }
            st, data, err = await fetch(
                client, "https://apis.map.qq.com/ws/place/v1/search", params,
                "tencent search",
            )
            tencent_search_data = data
            report_block("TENCENT /ws/place/v1/search (keyword=楼外楼 杭州)", st, data, err)
            if isinstance(data, dict):
                items = data.get("data")
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    tencent_id = items[0].get("id")
                    print(f"first result: title={items[0].get('title')!r} id={tencent_id}")
            if tencent_id:
                # 第 2 次：detail（官方形状 /ws/place/v1/detail?id=...&key=...）
                dparams = {"id": tencent_id, "key": tencent_key}
                st2, ddata, err2 = await fetch(
                    client, "https://apis.map.qq.com/ws/place/v1/detail", dparams,
                    "tencent detail",
                )
                report_block(f"TENCENT /ws/place/v1/detail id={tencent_id}", st2, ddata, err2)
        else:
            print("\nTENCENT: no tencent_map_key configured, skipped")

    print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
