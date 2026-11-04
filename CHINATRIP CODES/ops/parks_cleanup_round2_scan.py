# -*- coding: utf-8 -*-
"""新增 park 行增量扫描（2026-11-03）：只对 status='active' 的 park 行
跑普通公园三档分类，产出本次新增的「建议删」清单（此前 106 组已 inactive，
天然不在结果里）。输出 ops/parks_cleanup_round2_2026-11-03.md 供执行。"""

import csv
import io
import json
import re
from collections import Counter

from sqlalchemy import create_engine, text

DS = r"D:/CHINATRIP/DESIGN/POIS DATASOURCE"
OUT = r"D:/CHINATRIP/CHINATRIP CODES/ops/parks_cleanup_round2_2026-11-03.md"


def norm(s):
    if not s:
        return ""
    s = re.sub(r"[（(].*?[)）]", "", s)
    s = re.sub(r"[\s\-—–·、，,]", "", s)
    return s.strip()


def strip_suffix(s):
    for suf in ("风景名胜区", "旅游度假区", "风景区", "旅游区", "旅游景区", "景区"):
        if s.endswith(suf) and len(s) > len(suf) + 1:
            return s[: -len(suf)]
    return s


def city_of(*vals):
    out = set()
    for v in vals:
        if not v:
            continue
        for part in re.split(r"[、/]", v.replace("市", "").replace("省", "")):
            if part:
                out.add(part)
    return out


lists = {}


def add(reason, names, hints):
    lst = lists.setdefault(reason, [])
    for n in names:
        for v in {n, strip_suffix(n)}:
            if v:
                lst.append((v, hints or set()))


with open(f"{DS}/02_5A级旅游景区_358.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        add("5A", [norm(r["name_zh"])], city_of(r.get("province")))
with open(f"{DS}/04_国家级风景名胜区_244.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        add(
            "国家级风景名胜区",
            [norm(r["name_zh"])],
            city_of(r.get("province"), r.get("city")),
        )
with open(f"{DS}/05_国际旅行网站荐点_TA-LP-Viator.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        add(
            "国外平台推荐",
            [norm(r["name_zh"]), norm(r.get("alias_zh") or "")],
            city_of(r.get("city")),
        )
with open(f"{DS}/09_热门预约景点_门票预定.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        add(
            "热门预约景点",
            [norm(r["name_zh"]), norm(r.get("alias_zh") or "")],
            city_of(r.get("province"), r.get("city")),
        )
with open(
    f"{DS}/10_国际平台中国荐点_AI规划师与各国Agency.csv", encoding="utf-8-sig"
) as f:
    for r in csv.DictReader(f):
        zh = [
            m
            for m in re.findall(r"[（(]([^）)]*)[)）]", r.get("item_name") or "")
            if re.search(r"[\u4e00-\u9fff]", m) and len(norm(m)) >= 4
        ]
        add("国外平台推荐", [norm(z) for z in zh], city_of(r.get("city")))

eng = create_engine(
    "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip",
    connect_args={"connect_timeout": 3},
)
with eng.connect() as c:
    for nm, al, pcity in c.execute(
        text("select name_zh, name_aliases, city from pois where source='5a'")
    ):
        hints = city_of(pcity)
        add("5A", [norm(nm)], hints)
        if al:
            if isinstance(al, str):
                al = json.loads(al)
            add("5A", [norm(a) for a in (al or [])], hints)
    parks = c.execute(
        text(
            """select city, name_zh, source from pois
        where category='park' and status='active' and name_zh is not null
        order by city, name_zh"""
        )
    ).fetchall()

CITIES = [
    "北京",
    "上海",
    "南京",
    "苏州",
    "广州",
    "深圳",
    "成都",
    "杭州",
    "武汉",
    "重庆",
    "天津",
    "西安",
    "洛阳",
    "开封",
    "乌鲁木齐",
    "喀什",
    "兰州",
    "敦煌",
    "张家界",
    "长沙",
    "厦门",
    "福州",
    "昆明",
    "大理",
    "丽江",
    "贵阳",
    "哈尔滨",
    "沈阳",
    "大连",
    "济南",
    "青岛",
    "太原",
    "郑州",
    "合肥",
    "南昌",
    "无锡",
    "宁波",
    "温州",
    "珠海",
    "佛山",
    "东莞",
]
PROVS = [
    "广东",
    "江苏",
    "浙江",
    "四川",
    "湖北",
    "新疆",
    "陕西",
    "河南",
    "湖南",
    "云南",
    "山东",
    "山西",
    "福建",
    "甘肃",
    "贵州",
    "辽宁",
    "吉林",
    "黑龙江",
    "江西",
    "安徽",
    "河北",
]
KEEP = {"苏州园林曲园", "前海演艺公园"}
NOISE = re.compile(
    r"酒店|饭店|民宿|宾馆|公寓|庄园|地铁站|观光车|售票|VR馆|梦幻馆|亚朵|旧货市场|商旅|会议中心|颐养|公馆|悦榕庄|购物中心店"
)
NOISE2 = re.compile(r"剧场|游船|码头|演艺|广场")
SPECIAL_TOKENS = re.compile(
    r"国家|森林|湿地|植物园|动物园|园博园|博览园|世博|世园|花卉|遗址|纪念|郊野|温泉|恐龙|海洋|主题|欢乐|梦幻|童话|神话|卡丁|水世界|水公园|浪浪浪|乐园|花海|花田|花谷|地质|江滩|海滨|滨海|生态长廊|绿道|生态|科技|低碳|军事|国防|雕塑|艺术|文创|创意|工业|影视|古墟|古镇|古城|民俗|民族|山公园|体育|大观园|御花园|奥莱|farm|Farm"
)
KEEP_FAMOUS = {
    "北海公园",
    "世界公园",
    "北京大观园",
    "太子湾公园",
    "虎跑公园",
    "白塔公园",
    "方塔园",
    "古猗园",
    "醉白池",
    "课植园",
    "闻道园",
    "申园",
    "莫奈花园",
    "留园",
    "网师园",
    "耦园",
    "怡园",
    "可园",
    "退思园",
    "艺圃",
    "环秀山庄",
    "愚园",
    "宝墨园",
    "余荫山房",
    "梁园",
    "清晖园",
    "云台花园",
    "兰圃",
    "桂湖公园",
    "望江楼公园",
    "百花潭公园",
    "棠湖公园",
    "浣花溪公园",
    "塔子山公园",
    "解放公园",
    "中山公园",
    "愚园路历史风貌保护区",
    "郡王府",
    "月坛公园",
    "日坛公园",
    "玉渊潭公园",
    "陶然亭公园",
    "紫竹院公园",
    "世纪公园",
    "复兴公园",
    "鲁迅公园",
    "顾村公园",
    "星愿公园",
    "汽车博览公园",
    "越秀公园",
    "萝岗香雪公园",
    "燕子矶公园",
    "白鹭洲公园",
    "午朝门公园",
    "神策门公园",
    "白马公园",
    "香蜜公园",
    "深圳人才公园",
    "福田红树林生态公园",
    "宝安西湾红树林公园",
    "离堆公园",
    "鹅岭公园",
    "首义公园",
    "古林公园",
    "临平公园",
    # 新城市波补遗（2026-11-03 扫描新增）
    "水磨沟公园",
    "红山公园",
    "人民公园",
    # 第二轮人工复核保留：城市前缀躲过精确白名单/名字无特殊词但有来头
    "广州市越秀公园",
    "广州市黄花岗公园",
    "鸽子窝公园",
    "开封龙亭公园",
    "天波杨府公园",
    "丛台区丛台公园",
    "丛台区赵苑公园",
    "动植物公园",
    "柳侯公园",
    "世界风筝公园",
    "环翠楼公园",
}
PLAIN_PARK = re.compile(r"^[\u4e00-\u9fff0-9A-Za-z·]{1,7}公园$")
PLAIN_LAKE = re.compile(r"^[\u4e00-\u9fff0-9]{1,4}湖$")


def match(pcity, name):
    pn = norm(name)
    pn2 = pn
    if pcity:
        for pre in CITIES + PROVS:
            if pn2.startswith(pre):
                pn2 = pn2[len(pre) :]
                if pn2.startswith("市"):
                    pn2 = pn2[1:]
                break
    hits = []
    for reason, lst in lists.items():
        hit = None
        for n, hints in lst:
            if not n:
                continue
            if hints and pcity and pcity.replace("市", "") not in hints:
                continue
            if n == pn or (pn2 and n == pn2):
                hit = f"={n}"
                break
            if (n in pn or (pn2 and n in pn2)) and (
                len(n) >= 4
                or (len(n) >= 2 and (pn.startswith(n) or (pn2 and pn2.startswith(n))))
            ):
                hit = f"含{n}"
                break
            if len(pn) >= 3 and pn in n:
                hit = f"被含于{n}"
                break
        if hit:
            hits.append((reason, hit))
    return hits


def classify(city, name):
    if name in KEEP or name in KEEP_FAMOUS:
        return "keep"
    if SPECIAL_TOKENS.search(name):
        return "keep"
    if (
        city == "苏州"
        and re.match(r"^[\u4e00-\u9fff]{1,3}园$", name)
        and name != "苏州公园"
    ):
        return "keep"
    if PLAIN_PARK.match(name) or PLAIN_LAKE.match(name) or name == "三公园":
        return "ordinary"
    return "gray"


buckets = {"ordinary": [], "gray": [], "keep": []}
excluded, noise_rows, venue_rows = [], [], []
for city, nz, src in parks:
    nz = str(nz)
    if nz in KEEP or nz in KEEP_FAMOUS:
        buckets["keep"].append((city, nz, src))
        continue
    if NOISE.search(nz):
        noise_rows.append((city, nz, src))
        continue
    if NOISE2.search(nz):
        venue_rows.append((city, nz, src))
        continue
    hits = match(city, nz)
    if hits:
        excluded.append((city, nz, src, hits))
        continue
    buckets[classify(city, nz)].append((city, nz, src))

for key in buckets:
    seen, dedup = set(), []
    for row in buckets[key]:
        k = (row[0], row[1])
        if k not in seen:
            seen.add(k)
            dedup.append(row)
    buckets[key] = dedup

cc = Counter(c for c, *_ in buckets["ordinary"])
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# 公园清洗第二轮（2026-11-03，新增导入波增量扫描，仅 active 行）\n\n")
    f.write(
        "> 上轮 106 组普通公园已 inactive 不在扫描范围。"
        f"本轮 active park 共 {len(parks)} 行："
        f"建议删 {len(buckets['ordinary'])} / 灰区 {len(buckets['gray'])}"
        f" / 保留 {len(buckets['keep'])}；"
        f"四类名单命中 {len(excluded)}；"
        f"酒店误标 {len(noise_rows)}（recat 口径归类 hotel 不隐藏）；"
        f"场馆子点位 {len(venue_rows)}。\n\n"
    )
    f.write(f"## 建议删：普通地方性公园（{len(buckets['ordinary'])}）\n\n")
    for city, nz, src in buckets["ordinary"]:
        f.write(f"- {city or '—'}｜{nz}｜{src}\n")
    f.write(f"\n## 灰区（默认保留，{len(buckets['gray'])}）\n\n")
    for city, nz, src in buckets["gray"]:
        f.write(f"- {city or '—'}｜{nz}｜{src}\n")
    f.write(f"\n## 附A：酒店误标行（归 hotel 不隐藏，{len(noise_rows)}）\n\n")
    for city, nz, src in noise_rows:
        f.write(f"- {city or '—'}｜{nz}｜{src}\n")
    f.write(f"\n## 附B：场馆子点位（建议 entertainment，{len(venue_rows)}）\n\n")
    for city, nz, src in venue_rows:
        f.write(f"- {city or '—'}｜{nz}｜{src}\n")

print(
    f"active parks={len(parks)} ordinary={len(buckets['ordinary'])} "
    f"gray={len(buckets['gray'])} keep={len(buckets['keep'])} "
    f"excluded={len(excluded)} noise={len(noise_rows)} venue={len(venue_rows)}"
)
print()
print("=== 建议删（新增普通公园，active） ===")
for city, nz, src in buckets["ordinary"]:
    print(f"  {city or '—'} | {nz}")
print()
print("=== 灰区 ===")
for city, nz, src in buckets["gray"]:
    print(f"  {city or '—'} | {nz}")
print()
print("=== 附B 场馆（这轮直接改 entertainment） ===")
for city, nz, src in venue_rows:
    print(f"  {city or '—'} | {nz}")
print("saved:", OUT)
