"""重建 data/intl_platforms.csv（import_intl_platforms 的转写输入）。

原始转换器 build_intl_platforms_picks.py（工作区，未入库）已遗失，本脚本按
app/jobs/import_intl_platforms.py 文档头口径重建，输入为审阅包原始 sheet：

    DESIGN/POIS DATASOURCE/10_国际平台中国荐点_AI规划师与各国Agency.csv
    DESIGN/POIS DATASOURCE/11_短视频与社媒中国荐点_TikTok-Instagram-YouTube.csv

转换口径（2026-10-27 定稿 + 2026-11-06 重建核对）：
  类型过滤：tour/票务/住宿/餐饮/导览/频道/hashtag/账号/路线/城市榜/评分行不入
  （DROP_PAT 作用在整行繁转简文本上——英文头 Tour/Ticket/Show 与中文头一起判）；
  产品规则：红色/政治场所（纪念堂/大会堂等）不入；
  繁转简（内置常用字表）；集内去重（city+name_zh 归一后去重）。
输出 schema：city,name_zh,name_en,sites,aliases。

用法： python scripts/build_intl_platforms_picks.py [--out data/intl_platforms.csv]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHEETS = [
    REPO.parent
    / "DESIGN"
    / "POIS DATASOURCE"
    / "10_国际平台中国荐点_AI规划师与各国Agency.csv",
    REPO.parent
    / "DESIGN"
    / "POIS DATASOURCE"
    / "11_短视频与社媒中国荐点_TikTok-Instagram-YouTube.csv",
]

# platform 列 → 站点码（须与 import_intl_platforms._SITE_PRIORITY 一致；键为归一形）
PLATFORM_CODE = {
    "mindtrip": "mindtrip",
    "layla": "layla",
    "tripplanner.ai": "tripplanner",
    "wonderplan": "wonderplan",
    "guidegeek": "guidegeek",
    "trek": "trek",
    "surmai": "surmai",
    "pitravel": "pitravel",
    "letsfg": "letsfg",
    "sygictravel(tripomatic)": "sygic",
    "foursquare": "foursquare",
    "xiaohongshu": "xiaohongshu",
    "culturetrip": "culturetrip",
    "klook": "klook",
    "kkday": "kkday",
    "雄獅旅遊": "liontravel",
    "h.i.s.": "his",
    "jtb": "jtb",
    "tui": "tui",
    "yanolja": "yanolja",
    "waug": "waug",
    "creatrip": "creatrip",
    "itaka": "itaka",
    "tourtrans-вояж": "tourtrans",
    "youtube": "youtube",
    "tiktok": "tiktok",
    "instagram": "instagram",
    "watchmojo": "watchmojo",
}

CITY_MAP = {
    "beijing": "北京",
    "shanghai": "上海",
    "xi'an": "西安",
    "chengdu": "成都",
    "chongqing": "重庆",
    "guangzhou": "广州",
    "hangzhou": "杭州",
    "guilin": "桂林",
    "zhangjiajie": "张家界",
    "dalian": "大连",
    "sanya": "三亚",
    "hongkong": "香港",
    "hong kong": "香港",
    "suzhou": "苏州",
    "wuhan": "武汉",
    "nanjing": "南京",
    "北京": "北京",
    "上海": "上海",
    "西安": "西安",
    "成都": "成都",
    "重庆": "重庆",
    "广州": "广州",
    "杭州": "杭州",
    "桂林": "桂林",
    "张家界": "张家界",
    "大连": "大连",
    "三亚": "三亚",
    "香港": "香港",
    "苏州": "苏州",
    "武汉": "武汉",
    "南京": "南京",
    "乌镇": "乌镇",
    "凤凰": "凤凰",
    "长沙": "长沙",
    "洛阳": "洛阳",
    "澳门": "澳门",
    "乐山": "乐山",
    "海南": "海南",
}
# (city单元格包含, 名称) → 落城修正 / 跨城隔离
CITY_FIX = {("甘肃", ""): "敦煌"}
BLOCK_FIX = {("西安", "华山")}  # 华山在渭南，TUI 行按西安提及，不入

_T2S_PAIRS = (
    "宮宫園园廣广場场長长門门廳厅觀观纜缆車车動动獅狮嶺岭灣湾島岛廟庙壇坛頤颐"
    "楓枫橋桥鎮镇灘滩戲戏藝艺術术館馆麗丽綠绿樂乐運运遊游覽览飯饭點点據据豐丰"
    "閣阁樓楼關关嶽岳龍龙鳳凤灕漓築筑綢绸緞缎繡绣鑼锣鐘钟牆墙馬马華华興兴寶宝"
    "線线環环際际麼么這这們们對对國国会会來来東东無无为为與与種种個个樣样還还"
    "裡里講讲說说後后開开間间雙双銅铜電电視视黃黄靈灵飛飞發发製制遺遗産产"
)
_T2S = str.maketrans(_T2S_PAIRS[::2], _T2S_PAIRS[1::2])

CJK = re.compile(r"[一-鿿]")
HANGUL = re.compile(r"[가-힯]")
RUN = re.compile(r"[一-鿿0-9·]{2,}")

# 整行级过滤（繁转简后匹配；含英文头）
DROP_FULL = re.compile(
    r"一日游|半日游|[0-9一二兩三四五六七八九十]+\s*日[遊游學学观光觀光]?[遊游]?|純玩|纯玩"
    r"|\bTour|Ticket|Show|Hotel|Hostel|Cooking|Class|Experience|Private|Railway|Station"
    r"|Airport|Guide|Companion|Restaurant|Dinner|Lunch|Buffet|Circus|Acrobatic|Noodles"
    r"|Hot ?Pot|Package|Last ?Minute|Citywalk|citywalk|EDM|Rundreise|Wycieczk|Вояж"
    r"|巴士游|观光巴士|觀光巴士|車票|车票|船票|門票|门票|观光票|觀光票|套票|联票|聯票|杂技|雜技"
    r"|NT\$|US\$|円|руб|дней|ツアー|チケット|フリープラン|ホテル|호텔|номер|ночь"
    r"|[0-9]日間|[0-9]日観光|日帰り|発|год|мест|звёзд|体验|體驗|租賃|租赁|拍攝|拍摄"
    r"|导览|導覽|导赏|導賞|导游|導遊|导赏团|包車|包车|接送|接驳|接駁|定制|定製|私人|私享|私导"
    r"|酒店|旅館|旅馆|飯店|饭店|Resort|Motel|公寓|會所|会所"
    r"|餐廳|餐厅|食堂|面馆|麵館|飯館|饭馆|酒吧|烧烤|火鍋|火锅|烤鴨|烤鸭|生煎|餃子|饺子"
    r"|豆腐|龍蝦|龙虾|蟹|糖藕|蛋糕|美食|自助餐|晚餐|午餐|宴|麻婆|串串|冒菜|串焼"
    r"|纪念堂|紀念堂|大会堂|大會堂|中南海"  # 红色/政治场所不入（产品规则）
    r"|《|@|www\.|://|\.com|\.cn|官网|官方微信|售票处|售楼|门店|分店"
    r"|无条目|城市：|路线|路線|公里|另一|待证|待証|序号|快照|聚合榜|频道|hashtag"
    r"|专页|專頁|城市榜|榜单|清單|清单|账号|賬號|帳號|攻略|指南|磁浮|磁懸浮|磁悬浮"
    r"|[0-9.]+\s*分|[0-9]+评|订购|訂購|字幕|直播|打卡|vlog|Vlog|短剧|短劇"
    r"|住宿|总览|内容|世界遗产|世界遺産|[：→]|cuisine"
)
DROP_SUFFIXES = ("出发点",)
STRIP_PREFIX = re.compile(r"^榜单#\s*[0-9]+\s*|^「|」$|^\[[^\]]*\]")


def _t2s(s: str) -> str:
    return s.translate(_T2S)


def _norm(s: str) -> str:
    return "".join(s.split()).lower()


def _zh_from(text: str) -> str | None:
    """取最长中文段（中文/数字/·连续段）；须含 ≥2 个汉字。"""
    best = ""
    for m in RUN.finditer(text):
        seg = m.group(0)
        if len(CJK.findall(seg)) > len(CJK.findall(best)):
            best = seg
    best = best.strip("·")
    for suf in DROP_SUFFIXES:
        if best.endswith(suf):
            best = best[: -len(suf)]
    zh = best.strip("·")
    if len(CJK.findall(zh)) < 2 or len(zh) > 20:
        return None
    if len(zh) <= 3 and zh.endswith("区"):
        return None
    return _t2s(zh)


def _pick_zh_en(part: str) -> tuple[str | None, str | None]:
    """返回 (中文名, 英文名)。括号注解优先，其次整体。"""
    part = STRIP_PREFIX.sub("", part.strip())
    m = re.search(r"[（(]([^（）()]*)[)）]\s*$", part)
    inner, head = (m.group(1), part[: m.start()]) if m else (None, part)
    zh = None
    for cand in (inner, head):
        if cand:
            zh = _zh_from(cand)
            if zh:
                break
    if not zh:
        return None, None
    lat = re.sub(r"[（(][^（）()]*[)）]", " ", head)
    lat = re.sub(r"[^A-Za-z0-9 &''.-]", " ", lat)
    lat = re.sub(r"^[#\d\s]+", "", lat).strip(" -.")
    en = lat if 2 <= len(lat) <= 80 and re.search(r"[A-Za-z]", lat) else None
    return zh, en


def _extract_city(cell: str) -> str | None:
    low = cell.lower()
    found: list[str] = []
    for key in sorted(CITY_MAP, key=len, reverse=True):
        if key in low or key in cell:
            zh = CITY_MAP[key]
            if zh not in found:
                found.append(zh)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        return None
    for prefix, city in CITY_FIX:
        if prefix in cell:
            return city
    return None


def convert(rows_10: list[dict], rows_11: list[dict]) -> tuple[list[dict], list[str]]:
    picks: list[dict] = []
    dropped: list[str] = []
    seen: set[tuple[str, str]] = set()

    def add_pick(city: str, zh: str, en: str | None, site: str, where: str) -> None:
        key = (_norm(city), _norm(zh))
        if key in seen:
            return
        seen.add(key)
        picks.append(
            {
                "city": city,
                "name_zh": zh,
                "name_en": en or "",
                "sites": site,
                "aliases": "",
                "_src": where,
            }
        )

    def handle(row: dict, where: str) -> None:
        item = (row.get("item_name") or "").strip()
        city_cell = (row.get("city") or "").strip()
        ctype = (row.get("content_type") or row.get("type") or "").strip()
        platform = _norm(row.get("platform") or "")
        site = PLATFORM_CODE.get(platform)
        if ctype in {"频道", "hashtag", "账号", "視頻", "视频"} or item in {
            "-",
            "—",
            "",
        }:
            dropped.append(f"{where}: 类型/空行 [{ctype or item[:12]}]")
            return
        if not site:
            dropped.append(f"{where}: 平台未映射 [{row.get('platform')}]")
            return
        flat = _t2s(item)
        if HANGUL.search(item) or DROP_FULL.search(flat):
            dropped.append(f"{where}: 类型过滤 [{flat[:24]}]")
            return
        city = _extract_city(city_cell)
        if not city:
            dropped.append(f"{where}: 城市不可定 [{city_cell}]")
            return
        if any(city == c and name in flat for c, name in BLOCK_FIX):
            dropped.append(f"{where}: 跨城隔离 [{city}:{flat[:16]}]")
            return
        m = re.search(r"[（(]([^（）()]*、[^（）()]*)[)）]", item)
        if site == "tui" and m:
            got = 0
            for p in re.split(r"[、，,]", m.group(1)):
                zh, en = _pick_zh_en(p)
                if zh and not DROP_FULL.search(_t2s(zh)):
                    add_pick(city, zh, en, site, f"{where}#multi")
                    got += 1
                elif zh:
                    dropped.append(f"{where}: multi过滤 [{zh}]")
            if not got:
                dropped.append(f"{where}: 多POI格无有效名 [{flat[:30]}]")
            return
        zh, en = _pick_zh_en(item)
        if not zh:
            dropped.append(f"{where}: 无中文名 [{flat[:30]}]")
            return
        if DROP_FULL.search(_t2s(zh)):
            dropped.append(f"{where}: 名称过滤 [{zh}]")
            return
        add_pick(city, zh, en, site, f"{where}")

    for i, row in enumerate(rows_10, 2):
        handle(row, f"10#{i}")
    for i, row in enumerate(rows_11, 2):
        handle(row, f"11#{i}")
    return picks, dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="重建 intl_platforms.csv（10/11 号转写）"
    )
    parser.add_argument("--out", default=str(REPO / "data" / "intl_platforms.csv"))
    args = parser.parse_args(argv)

    rows_10: list[dict] = []
    rows_11: list[dict] = []
    for path, bucket in zip(SHEETS, (rows_10, rows_11)):
        if not path.exists():
            print(f"missing sheet: {path}", file=sys.stderr)
            return 1
        with open(path, encoding="utf-8-sig", newline="") as fh:
            bucket.extend(csv.DictReader(fh))

    picks, dropped = convert(rows_10, rows_11)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["city", "name_zh", "name_en", "sites", "aliases"]
        )
        w.writeheader()
        for p in picks:
            w.writerow({k: p[k] for k in w.fieldnames})
    print(f"picks={len(picks)} dropped={len(dropped)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
