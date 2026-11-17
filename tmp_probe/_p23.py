# -*- coding: utf-8 -*-
import io, shutil, re
wp = r"D:\tmp_ct_wishdup\CHINATRIP CODES\app\services\agent\plan.py"
shutil.copyfile(wp, wp + ".bak_all")
t = io.open(wp, encoding="utf-8", newline=None).read()

# revert hunk (b): replace new head with old head (reconstruct by replacing the new block)
start = t.index('        rows = groups.get("wishlist", []) + groups.get("scheduled", [])\n')
end_marker = "        for it in picked_rows:\n            name = str(it.get(\"name\") or \"\")\n            row_itin = it.get(\"itinerary_id\")\n"
end = t.index(end_marker) + len(end_marker)
new_head = t[start:end]
old_head = '''        rows = groups.get("wishlist", []) + groups.get("scheduled", [])
        for it in rows:
            # 2026-10-30 深夜：行按名字全局去重（跨会话共享）——凡命中本会
            # 话心愿名的行即本用户当前心愿行，无条件换绑当前行程；旧 id 记
            # 入 linked_itins 供追溯。
            name = str(it.get("name") or "")
            if not name or not any(_name_dup(name, n) for n in names):
                continue
            # 2026-11-13（用户拍板「心愿单的城市必须在插入的时候就标注
            # 城市」+ 陕历博串行程案）：行城是权威——已定城且不在本次
            # 行程的，不换绑、不翻已排期（旧行为按名字无条件 force 换绑，
            # 西安心愿被挂到成都重庆行程上）。
            row_city = _norm_city(str(it.get("city") or "")).removesuffix("市")
            # 2026-11-13（用户报「已排期里都是上海行程，可是行程根本没有
            # 上海」）：城闸以**行程真正有落点的城**为准——逐日看条目城，某天
            # 一条带城的都没有才回退 base_city；全程住西安的 上海→西安→上海
            # 行程不再把上海心愿吸收进来（cities 只是路线端点）。
            trip_cities_here: set[str] = set()
            for day in session.plan.days:
                day_cities = {
                    _norm_city(i.city or "").removesuffix("市")
                    for i in day.items
                    if isinstance(i, VisitItem) and (i.city or "").strip()
                }
                if not day_cities and (day.base_city or "").strip():
                    day_cities = {
                        _norm_city(day.base_city or "").removesuffix("市")
                    }
                trip_cities_here |= day_cities
            if not trip_cities_here:
                trip_cities_here = {
                    _norm_city(c or "").removesuffix("市")
                    for c in session.cities
                    if (c or "").strip()
                }
            if row_city and trip_cities_here and row_city not in trip_cities_here:
                logger.info(
                    "plan: wish row off-trip skip %s city=%s trip_cities=%s",
                    name,
                    row_city,
                    session.cities,
                )
                continue
            row_itin = it.get("itinerary_id")
'''
t = t[:start] + old_head + t[end:]
io.open(wp, "w", encoding="utf-8", newline="\r\n").write(t)
print("reverted (b) in worktree")
