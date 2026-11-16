"""规划页外链实检 job（2026-11-16 用户拍板「post 出去的链接必须先验证」）。

审计逻辑已收敛到 app/services/link_audit.py（写入口共用同一套判定）；
本 job 负责**全量重扫**：poi_access_services(active) 的 ticket/official/source
+ pois 的 booking_url/website，写 app/data/verified_links.json（读侧白名单）。

用法（在 CHINATRIP CODES 目录跑）：
    python -m app.jobs.verify_access_links               # 实检并写白名单
    python -m app.jobs.verify_access_links --dry-run     # 只打印，不写文件
    python -m app.jobs.verify_access_links --out app/data/verified_links.json
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import text

from app.db import get_session_factory
from app.services import link_audit

logger = logging.getLogger(__name__)


def collect_urls(session) -> dict[str, list[str]]:
    urls: dict[str, list[str]] = {}

    def add(raw, source):
        value = link_audit.normalize(raw)
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
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    factory = get_session_factory()
    with factory() as session:
        urls = collect_urls(session)
    logger.info("unique urls: %d", len(urls))

    links: dict[str, dict] = {}
    for url in sorted(urls):
        entry = link_audit.audit(url)
        entry["sources"] = urls[url]
        links[url] = entry
        logger.info("[%s] %s", entry["verdict"], url)

    dead = [u for u, e in links.items() if e["verdict"] == "dead"]
    for url in dead:
        logger.warning("dead: %s %s", url, links[url]["sources"][:2])
    if args.dry_run:
        logger.info("dry-run: 不写白名单")
        return 0
    target = link_audit.write_whitelist(
        links, args.out or link_audit.WHITELIST_PATH
    )
    logger.info("白名单已写入 %s", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
