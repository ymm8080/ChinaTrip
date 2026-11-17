"""外链审计（2026-11-16 用户拍板「audit before input any url」）。

单一事实源：任何 URL **写进数据库 / 写进白名单之前**都先过这里的 HTTP 实测——
班次导入（import_access_services）、预约规则核对（refresh_reservation_rules）、
演出导入（import_shows）都调它；读侧 legs._url 只认白名单
（app/data/verified_links.json）。verdict 语义与 verify_access_links job 一致：

* ok           —— 2xx/3xx；
* ok_retry     —— 首次失败、重试通过（偶发抖动）；
* ok_http_only —— https 握手失败、http 200（display_url 换成 http）；
* blocked_bot  —— 401/403/412/429/432（反爬拦截，浏览器可开，保留展示）；
* dead         —— 网络失败/非反爬 4xx/5xx/DNS 失败——**不允许入库**。

用法：
    from app.services import link_audit
    url, entry = link_audit.audit_or_none(raw)        # dead→(None, entry)
    link_audit.audit_row_fields(row, ("ticket_url",)) # 就地清洗死链+落白名单
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CTX = ssl.create_default_context()
BLOCK_CODES = {401, 403, 412, 429, 432}
USABLE_VERDICTS = {"ok", "ok_retry", "ok_http_only", "blocked_bot"}

WHITELIST_PATH = Path(__file__).resolve().parents[1] / "data" / "verified_links.json"


def normalize(raw) -> str:
    """裸域名补 https；空值回空串。"""
    value = str(raw or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value.lstrip("/")
    return value


def _get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
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


def audit(url: str, *, timeout: int = 30) -> dict:
    """实检一条 URL，返回含 verdict/display_url 的条目。"""
    url = normalize(url)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry: dict = {
        "url": url,
        "verdict": "dead",
        "display_url": "",
        "status": None,
        "final_url": "",
        "checked_at": now,
    }
    if not url:
        entry["verdict"] = "unknown"
        return entry
    first = _get(url, timeout=timeout)
    entry.update(
        status=first.get("status"),
        final_url=first.get("final_url") or "",
        title=first.get("title") or "",
        detail=first,
    )
    if first["ok"]:
        entry["verdict"] = "ok"
        return entry
    if first.get("status") in BLOCK_CODES:
        entry["verdict"] = "blocked_bot"
        return entry
    retry = _get(url, timeout=timeout)
    entry["retry"] = retry
    if retry["ok"]:
        entry["verdict"] = "ok_retry"
        return entry
    if retry.get("status") in BLOCK_CODES:
        entry["verdict"] = "blocked_bot"
        return entry
    if url.startswith("https://"):
        http_url = "http://" + url[len("https://") :]
        http_res = _get(http_url, timeout=timeout)
        entry["http"] = http_res
        if http_res["ok"]:
            entry["verdict"] = "ok_http_only"
            entry["display_url"] = http_url
            return entry
    entry["verdict"] = "dead"
    return entry


def usable(verdict: str | None) -> bool:
    return str(verdict or "").strip().lower() in USABLE_VERDICTS


def _load_links(path: Path | None = None) -> dict:
    target = path or WHITELIST_PATH
    try:
        payload = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    links = payload.get("links") if isinstance(payload, dict) else None
    return links if isinstance(links, dict) else {}


def write_whitelist(links: dict, path: Path | None = None) -> Path:
    """整表白名单落盘（tmp+replace，供 job 全量刷新）。"""
    target = Path(path or WHITELIST_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "app.services.link_audit",
        "counts": {
            "total": len(links),
            "dead": sum(1 for e in links.values() if e.get("verdict") == "dead"),
            "ok": sum(
                1 for e in links.values() if str(e.get("verdict", "")).startswith("ok")
            ),
            "blocked_bot": sum(
                1 for e in links.values() if e.get("verdict") == "blocked_bot"
            ),
        },
        "links": links,
    }
    tmp = str(target) + ".tmpwrite"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, target)
    return target


def record(entries: list[dict], path: Path | None = None) -> int:
    """把刚审计的条目合并进白名单（读侧 mtime 热更新，新链接立即可用）。"""
    fresh = [e for e in entries if isinstance(e, dict) and e.get("url")]
    if not fresh:
        return 0
    links = _load_links(path)
    for entry in fresh:
        links[entry["url"]] = entry
    write_whitelist(links, path)
    return len(fresh)


def audit_or_none(
    raw, *, timeout: int = 30, record_entry: bool = True
) -> tuple[str | None, dict | None]:
    """审计一条 URL：可用返回 (展示地址, 条目)，死链返回 (None, 条目)。

    展示地址：ok/ok_http_only 有 display_url 时用它（站点只支持 http）。
    审计结果同时写回白名单（record_entry=False 时只审计不落盘，供测试/预检）。
    """
    url = normalize(raw)
    if not url:
        return None, None
    entry = audit(url, timeout=timeout)
    if record_entry:
        record([entry])
    if not usable(entry.get("verdict")):
        return None, entry
    return str(entry.get("display_url") or url), entry


def audit_row_fields(
    row: dict,
    fields: tuple[str, ...],
    *,
    timeout: int = 30,
    record_entry: bool = True,
) -> list[str]:
    """就地审计 dict 里的 URL 字段：死链置 None，可用则回写展示地址。

    返回被剔除的死链清单（"field:value"），供调用方日志/汇总。
    """
    dead: list[str] = []
    for field in fields:
        raw = row.get(field)
        if not raw:
            continue
        url, entry = audit_or_none(raw, timeout=timeout, record_entry=record_entry)
        if url is None:
            dead.append(f"{field}:{raw}")
            row[field] = None
        else:
            row[field] = url
    return dead
