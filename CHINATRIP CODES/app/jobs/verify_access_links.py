"""规划页外链实检 job（2026-11-16 用户拍板「post 出去的链接必须先验证」）。

用法（在 CHINATRIP CODES 目录跑）：
    python -m app.jobs.verify_access_links               # 实检并写白名单
    python -m app.jobs.verify_access_links --dry-run     # 只打印，不写文件
    python -m app.jobs.verify_access_links --out app/data/verified_links.json

检查范围 = 规划页会渲染的全部外链：
* poi_access_services（active）的 ticket_url / official_url / source_url；
* pois 的 booking_url / website（行程卡预约按钮与腿行「官网 →」的兜底）。

分类（verdict）：
* ok          —— 首次即 2xx/3xx；
* ok_retry    —— 首次失败、重试通过（偶发抖动，仍算验证通过）；
* ok_http_only—— https 握手失败但 http 200（站点不支持 TLS，展示地址换 http）；
* blocked_bot —— 401/403/412/429/432（反爬拦截，浏览器可开，保留展示）；
* dead        —— 网络失败/4xx(非反爬)/5xx/DNS 失败，一律不进白名单。
读取侧（legs._url）只放行前四类；dead/未在白名单=不出链接。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.db import get_session_factory

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_CTX = ssl.create_default_context()
_BLOCK_CODES = {401, 403, 412, 429, 432}
_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "verified_links.json"


def _norm(raw) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value.lstrip("/")
    return value


def _get(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            body = resp.read(20000).decode("utf-8", "replace")
            match = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
            return {
                "status": resp.getcode(),
                "final_url": resp.geturl(),
                "ok": 200 <= resp.getcode() < 400,
                "title": match.group(1).strip()[:120] if match else "",
            }
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "ok": False, "error": f"HTTPError {exc.code}"}
    except Exception as exc:  # noqa: BLE001 - 任何网络异常都当失败
        return {"status": None, "ok": False, "error": repr(exc)[:200]}


def classify(url: str) -> dict:
    """实检一条 URL，返回含 verdict/display_url 的条目。"""
    first = _get(url)
    result = {"verdict": "", "display_url": "", "detail": first}
    if first["ok"]:
        result["verdict"] = "ok"
        return result
    if first.get("status") in _BLOCK_CODES:
        result["verdict"] = "blocked_bot"
        return result
    # 重试一次（偶发抖动）
    retry = _get(url)
    result["retry"] = retry
    if retry["ok"]:
        result["verdict"] = "ok_retry"
        return result
    if retry.get("status") in _BLOCK_CODES:
        result["verdict"] = "blocked_bot"
        return result
    # https 握手失败类 → 换 http 再试
    if url.startswith("https://"):
        http_url = "http://" + url[len("https://"):]
        http_res = _get(http_url)
        result["http"] = http_res
        if http_res["ok"]:
            result["verdict"] = "ok_http_only"
            result["display_url"] = http_url
            return result
    result["verdict"] = "dead"
    return result


def collect_urls(session) -> dict[str, list[str]]:
    urls: dict[str, list[str]] = {}

    def add(raw, source):
        value = _norm(raw)
        if value:
            urls.setdefault(value, []).append(source)

    rows = session.execute(
        text(
            """
            SELECT poi_name, service_name, ticket_url, official_url, source_url
              FROM poi_access_services WHERE active IS TRUE
            """
        )
    ).all()
    for poi, svc, ticket, official, source in rows:
        add(ticket, f"access.ticket:{poi}/{svc}")
        add(official, f"access.official:{poi}/{svc}")
        add(source, f"access.source:{poi}/{svc}")
    rows = session.execute(
        text(
            """
            SELECT name_zh, booking_url, website FROM pois
             WHERE (booking_url IS NOT NULL AND btrim(booking_url) <> '')
                OR (website IS NOT NULL AND btrim(website) <> '')
            """
        )
    ).all()
    for name, booking, website in rows:
        add(booking, f"pois.booking:{name}")
        add(website, f"pois.website:{name}")
    return urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="规划页外链实检")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    factory = get_session_factory()
    with factory() as session:
        urls = collect_urls(session)
    logger.info("unique urls: %d", len(urls))

    links: dict[str, dict] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for url in sorted(urls):
        entry = classify(url)
        entry["sources"] = urls[url]
        entry["checked_at"] = now
        links[url] = entry
        logger.info("[%s] %s", entry["verdict"], url)

    dead = [u for u, e in links.items() if e["verdict"] == "dead"]
    payload = {
        "generated_at": now,
        "source": "app.jobs.verify_access_links",
        "counts": {
            "total": len(links),
            "dead": len(dead),
            "ok": sum(1 for e in links.values() if e["verdict"].startswith("ok")),
            "blocked_bot": sum(
                1 for e in links.values() if e["verdict"] == "blocked_bot"
            ),
        },
        "links": links,
    }
    logger.info("counts: %s", payload["counts"])
    for url in dead:
        logger.warning("dead: %s %s", url, links[url]["sources"][:2])
    if args.dry_run:
        logger.info("dry-run: 不写白名单")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(args.out) + ".tmpwrite"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, args.out)
    logger.info("白名单已写入 %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
