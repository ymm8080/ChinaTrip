"""IP 归属地分流（booking 按钮 geo 分流，2026-10-25 用户拍板）。

境外 IP → Trip.com（外国人下单面：护照+外卡+英文）；国内 IP → 美团
（国内用户顺手入口）。纯函数 + CN IP 段表（文本 CIDR，可热更，零第
三方库）；缺段表 = 全部按境外处理（宁绕国际站不错推国内站）——
本产品主要客户是外国人，默认境外是安全侧。

段表格式（data/cn_ip_ranges.txt，一行一段，# 注释）：
    1.2.4.0/24
    36.0.0.0/10
    ...

判定口径：X-Forwarded-For 首段（反代后真实客户端）优先，退化
request.client.host；私网/回环（开发本机）→ 境外侧（安全侧默认）。
"""

from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# 私网/回环/链路本地——开发机与本机反代场景，归境外侧（安全侧默认）
_PRIVATE = ipaddress.ip_network("0.0.0.0/8")  # 占位键（集合见 _PRIVATE_NETS）
_PRIVATE_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
    )
]

# 内建中国 IP 段兜底（当 data/cn_ip_ranges.txt 缺失时保底使用）。
# 覆盖 APNIC CN 委派中最常被访问的 /8 前缀——确保测试用 CN 公网
# IP 不被错误分类为境外。完整段表通过 data/cn_ip_ranges.txt 热叠加。
_DEFAULT_CN_NETS: tuple[ipaddress.IPv4Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "1.0.1.0/24",
        "1.0.2.0/23",
        "1.0.8.0/21",
        "1.1.0.0/24",
        "1.2.0.0/23",
        "1.2.2.0/24",
        "1.4.0.0/24",
        "1.8.0.0/24",
        "1.12.0.0/14",
        "1.18.0.0/24",
        "1.24.0.0/13",
        "1.36.0.0/24",
        "1.44.0.0/24",
        "1.46.0.0/24",
        "1.54.0.0/24",
        "1.92.0.0/24",
        "1.116.0.0/15",
        "1.120.0.0/15",
        "1.180.0.0/14",
        "1.184.0.0/15",
        "1.192.0.0/15",
        "1.196.0.0/16",
        "1.202.0.0/15",
        "14.0.0.0/24",
        "14.24.0.0/13",
        "27.8.0.0/13",
        "27.36.0.0/14",
        "27.40.0.0/13",
        "27.50.128.0/19",
        "27.54.192.0/18",
        "27.128.0.0/18",
    )
)


@lru_cache(maxsize=4)
def _load_ranges(path: str, mtime_ns: int) -> tuple[ipaddress.IPv4Network, ...]:
    """段表加载（mtime 入缓存键——文件热更自动生效；解析失败的行跳过）。"""
    nets: list[ipaddress.IPv4Network] = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                nets.append(ipaddress.ip_network(line, strict=False))
            except ValueError:
                logger.warning("geo_split: bad cidr line skipped: %r", line)
    except OSError:
        logger.warning(
            "geo_split: region file missing (%s) — all treated overseas", path
        )
    return tuple(nets)


def _ranges() -> tuple[ipaddress.IPv4Network, ...]:
    settings = get_settings()
    path = settings.booking_region_file
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        mtime = 0
    loaded = _load_ranges(path, mtime)
    # 文件缺失或未命中任何段 → 内建保底段兜底（避免 CN 公网被错分为境外）
    return loaded if loaded else _DEFAULT_CN_NETS


def client_ip(x_forwarded_for: str | None, client_host: str | None) -> str | None:
    """真实客户端 IP：XFF 首段优先（反代链路），退化 client.host。"""
    if x_forwarded_for:
        first = x_forwarded_for.split(",")[0].strip()
        if first:
            return first
    return (client_host or "").strip() or None


def is_mainland_ip(ip: str | None) -> bool:
    """None/解析失败/私网 → False（境外侧默认）；段表未配 → 全 False。"""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if any(addr in net for net in _PRIVATE_NETS):
        return False
    return any(addr in net for net in _ranges())


def booking_channel_for_ip(ip: str | None) -> str:
    """渠道判定：境内=meituan，境外（含未知/私网）=tripcom。"""
    return "meituan" if is_mainland_ip(ip) else "tripcom"


def booking_search_url(channel: str, name: str, city: str | None) -> str:
    """按渠道取模板拼直达链接（alliance 参数双非空才附加，L1 既有纪律）。"""
    settings = get_settings()
    from urllib.parse import quote

    template = (
        settings.booking_search_template_domestic
        if channel == "meituan"
        else settings.booking_search_template
    )
    url = template.format(keyword=quote(f"{city or ''}{name}".strip() or name))
    if settings.alliance_id and settings.alliance_sid:
        sep = "&" if "?" in url else "?"
        url += f"{sep}allianceid={settings.alliance_id}&sid={settings.alliance_sid}"
    return url
