"""临时对比脚本：amap / qunar 评分与 ctrip 基准的贴近度（三方同 POI 实测）。

样本：rating_source='amap' 的优先组行（unesco/5a/curated/博物馆打头）。
每行三方取分：amap=库存量值；ctrip=详情页新鲜解析；qunar=列表发现+详情
aria-label 主评分。输出逐行三方分与 |偏差|。
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.db import get_session_factory  # noqa: E402
from app.models import Poi  # noqa: E402
from app.services.ctrip_hours import CITY_SLUGS, get_ctrip_hours  # noqa: E402

_QUNAR_SLUGS_PATH = Path(__file__).resolve().parents[1] / "app/jobs/enrich_qunar_duration.py"


def _load_qunar_slugs() -> dict[str, str]:
    src = _QUNAR_SLUGS_PATH.read_text(encoding="utf-8")
    m = re.search(r"QUNAR_CITY_SLUGS\s*=\s*\{(.*?)\n\}", src, re.S)
    out: dict[str, str] = {}
    if m:
        for k, v in re.findall(r'"([^"]+)":\s*"([^"]+)"', m.group(1)):
            out[k] = v
    return out


def _resolve_city(city: str) -> str | None:
    """与 enrich_ctrip_detail 同口径：原名 → 县级上卷 → slug 城名。"""
    from app.jobs.enrich_ctrip_detail import _county_map, _load_extra_slugs

    slugs = {**CITY_SLUGS, **_load_extra_slugs()}
    name = (city or "").strip().removesuffix("市")
    if name in slugs:
        return name
    county = _county_map()
    raw = (city or "").strip()
    pref = None
    if raw in county:
        pref = county[raw]
    else:
        for suf in ("林区", "特区", "自治县", "自治旗", "市", "县", "区", "旗"):
            if raw + suf in county:
                pref = county[raw + suf]
                break
    if pref:
        pref = pref.removesuffix("市")
        if pref in slugs:
            return pref
    return None


async def _ctrip_score(city: str, name: str) -> tuple[float | None, str]:
    resolved = _resolve_city(city)
    if not resolved:
        return None, "no-slug"
    reader = get_ctrip_hours()
    try:
        fields = await reader.detail_fields_for(resolved, name)
    except Exception as e:  # noqa: BLE001
        return None, f"err:{type(e).__name__}"
    if not fields:
        return None, "no-page"
    return fields.get("rating"), "ok"


async def _qunar_score(city: str, name: str, client: httpx.AsyncClient) -> tuple[float | None, str]:
    slugs = _load_qunar_slugs()
    slug = slugs.get((city or "").strip().removesuffix("市"))
    if not slug:
        return None, "no-slug"
    variants = [name]
    core = re.sub(r"(风景名胜区|旅游景区|旅游区|风景区|度假区|景区|遗址公园|博物馆|馆|园|街)$", "", name)
    if len(core) >= 2:
        variants.append(core)
    for v in variants:
        # 1) 列表页找 poi_id（1-2 页）
        pid = None
        for page in (1, 2):
            try:
                r = await client.get(
                    f"https://sight.qunar.com/list?city={slug}&page={page}"
                )
            except Exception:  # noqa: BLE001
                return None, "list-err"
            pairs = re.findall(
                r'"url":\s*"https://sight\.qunar\.com/(\d{6,})"\s*,\s*"name"\s*:\s*"([^"]{2,24})"',
                r.text,
            ) or re.findall(
                r'"name"\s*:\s*"([^"]{2,24})"[^}]{0,120}?"url":\s*"https://sight\.qunar\.com/(\d{6,})"',
                r.text,
            )
            pairs = [
                (a, b) if isinstance(a, str) and a.isdigit() else (b, a) for a, b in pairs
            ]
            for qid, qname in pairs:
                if v.replace(" ", "") in qname.replace(" ", "") or qname in v:
                    pid = qid
                    break
            if pid:
                break
        if not pid:
            continue
        # 2) 详情页主评分（aria-label 第一个 = 主条目）
        try:
            d = await client.get(f"https://sight.qunar.com/{pid}")
        except Exception:  # noqa: BLE001
            return None, "detail-err"
        m = re.search(r'"aria-label\\?":\s*\\"([\d.]+) 分', d.text) or re.search(
            r'"aria-label":"([\d.]+) 分', d.text
        )
        if m:
            return float(m.group(1)), f"ok({pid})"
        return None, f"no-score({pid})"
    return None, "not-in-list"


async def main() -> None:
    from app.services.source_tier import SOURCE_PRIORITY

    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    with get_session_factory()() as s:
        rows = (
            s.query(Poi)
            .filter(
                Poi.status == "active",
                Poi.rating_source == "ctrip",
                Poi.rating.isnot(None),
                Poi.city.in_(("北京", "西安", "上海", "杭州", "成都", "重庆", "广州", "苏州")),
                func.length(Poi.name_zh) <= 10,
            )
            .all()
        )
        rows.sort(key=lambda r: (rank.get(r.source, 99), str(r.id)))
        sample = rows[:10]
        print(f"样本 {len(sample)} 行（amap 评分行，优先组打头）:")
        for r in sample:
            print(f"  {r.source:10} {r.city[:8]:8} {(r.name_zh or '')[:18]:18} amap={r.rating}")

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        timeout=15,
        follow_redirects=True,
    ) as client:
        results = []
        for row in sample:
            name = (row.name_zh or "").strip()
            c_score, c_note = float(row.rating), "db"
            q_score, q_note = await _qunar_score(row.city, name, client)
            results.append((row, float(row.rating), c_score, c_note, q_score, q_note))
            await asyncio.sleep(1)

    print("\n=== 逐行对比（基准=ctrip）===")
    a_d, q_d, a_n, q_n = [], [], 0, 0
    for row, a, c, cn, q, qn in results:
        da = f"{abs(a - c):.1f}" if (a is not None and c is not None) else "-"
        dq = f"{abs(q - c):.1f}" if (q is not None and c is not None) else "-"
        if a is not None and c is not None:
            a_d.append(abs(a - c)); a_n += 1
        if q is not None and c is not None:
            q_d.append(abs(q - c)); q_n += 1
        print(
            f"  {row.name_zh[:14]:14} amap={a}({cn}) ctrip={c}({cn[0] if False else 'base' if c else cn}) qunar={q}({qn}) |Δa={da} Δq={dq}"
        )
    if a_d:
        print(f"\namap vs ctrip: n={a_n} 平均|Δ|={sum(a_d)/len(a_d):.2f}")
    if q_d:
        print(f"qunar vs ctrip: n={q_n} 平均|Δ|={sum(q_d)/len(q_d):.2f}")
    print("覆盖率（本样本内拿到分）: amap 100%（存量） ctrip", f"{sum(1 for _,_,c,_,_,_ in results if c)}/{len(results)}", "qunar", f"{sum(1 for _,_,_,_,q,_ in results if q)}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
