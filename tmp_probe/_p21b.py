# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:110])
    t = t.replace(old, new)

sub('''from app.services.trip_items import (
    STATUS_BOOKED,
    STATUS_SCHEDULED,
    STATUS_UNWANTED,
    STATUS_WISHLIST,
    strip_scheduled_note,
)
''', '''from app.services.trip_items import (
    STATUS_BOOKED,
    STATUS_SCHEDULED,
    STATUS_UNWANTED,
    STATUS_WISHLIST,
    _wish_key,
    strip_scheduled_note,
)
''')

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
new_head = '''        rows = groups.get("wishlist", []) + groups.get("scheduled", [])
        # 2026-11-13（用户报「已排期里都是上海行程…」）：城闸以**行程真正
        # 有落点的城**为准——逐日看条目城，某天一条带城的都没有才回退
        # base_city；全程住西安的 上海→西安→上海 行程不再把上海心愿吸收
        # 进来（cities 只是路线端点）。行级判定共用，只算一次。
        trip_cities_here: set[str] = set()
        for day in session.plan.days:
            day_cities = {
                _norm_city(i.city or "").removesuffix("市")
                for i in day.items
                if isinstance(i, VisitItem) and (i.city or "").strip()
            }
            if not day_cities and (day.base_city or "").strip():
                day_cities = {_norm_city(day.base_city or "").removesuffix("市")}
            trip_cities_here |= day_cities
        if not trip_cities_here:
            trip_cities_here = {
                _norm_city(c or "").removesuffix("市")
                for c in session.cities
                if (c or "").strip()
            }
        cur_sid = self._wish_draft_session(session)

        def _wish_row_eligible(row: dict) -> bool:
            """2026-11-14（用户报「已排期里同一个心愿出现两三条」）认领闸：
            名字命中 + 城市在行程内 + 不是别的会话的草稿 + 不是别的行程的行。
            旧行为按名字跨会话/跨行程无条件吸收——重新规划每开一局就新建
            一行再全量挂进来，已排期于是同一心愿越滚越多。"""
            name = str(row.get("name") or "")
            if not name or not any(_name_dup(name, n) for n in names):
                return False
            row_city = _norm_city(str(row.get("city") or "")).removesuffix("市")
            if row_city and trip_cities_here and row_city not in trip_cities_here:
                logger.info(
                    "plan: wish row off-trip skip %s city=%s trip_cities=%s",
                    name,
                    row_city,
                    session.cities,
                )
                return False
            row_draft = str(row.get("draft_session_id") or "")
            if row_draft and row_draft != (cur_sid or ""):
                return False
            row_itin = row.get("itinerary_id")
            if row_itin and row_itin != itin:
                return False
            return True

        bound_rows: list[dict] = []
        free_rows: list[dict] = []
        for it in rows:
            if _wish_row_eligible(it):
                (bound_rows if it.get("itinerary_id") == itin else free_rows).append(it)
        # 每个心愿名只认领一行：已挂本行程的优先（已排期且最早建的留任），
        # 其次无绑定正式行；同名多行挂在本行程 = 历史重复，软删自愈。
        picked_rows: list[dict] = []
        seen_keys: set[str] = set()
        drop_rows: list[dict] = []
        for it in sorted(
            bound_rows,
            key=lambda r: (
                r.get("status") != STATUS_SCHEDULED,
                str(r.get("created_at") or ""),
            ),
        ):
            key = _wish_key(str(it.get("name") or ""))
            if key in seen_keys:
                drop_rows.append(it)
            else:
                seen_keys.add(key)
                picked_rows.append(it)
        for it in free_rows:
            key = _wish_key(str(it.get("name") or ""))
            if key not in seen_keys:
                seen_keys.add(key)
                picked_rows.append(it)
        for extra in drop_rows:
            try:
                self._trip_items.delete(extra["id"], actor=session.device_id)
                logger.info(
                    "plan: duplicate wish row dropped %s id=%s",
                    extra.get("name"),
                    extra["id"],
                )
            except Exception:
                logger.warning(
                    "plan: duplicate wish row drop failed id=%s",
                    extra.get("id"),
                    exc_info=True,
                )
        for it in picked_rows:
            name = str(it.get("name") or "")
            row_itin = it.get("itinerary_id")
'''
sub(old_head, new_head)

old_sel = '''        rows = [r for g in groups.values() for r in g]
        for item in planned:
            row = next(
                (
                    r
                    for r in rows
                    if (item.poi_id and r.get("poi_id") and r["poi_id"] == item.poi_id)
                    or _name_dup(str(r.get("name") or ""), item.name)
                ),
                None,
            )
            if row is None:
'''
new_sel = '''        rows = [r for g in groups.values() for r in g]
        cur_sid = self._wish_draft_session(session)
        for item in planned:
            matches = [
                r
                for r in rows
                if (item.poi_id and r.get("poi_id") and r["poi_id"] == item.poi_id)
                or _name_dup(str(r.get("name") or ""), item.name)
            ]
            # 2026-11-14：别会话草稿/别行程的行不认领；已挂本行程的行优先，
            # 其次无绑定行——防同一心愿的多行被轮流翻牌成已排期。
            matches = [
                r
                for r in matches
                if not str(r.get("draft_session_id") or "")
                or str(r.get("draft_session_id")) == (cur_sid or "")
            ]
            bound_rows = [r for r in matches if r.get("itinerary_id") == itin]
            if bound_rows:
                row = sorted(
                    bound_rows,
                    key=lambda r: (
                        r.get("status") != STATUS_SCHEDULED,
                        str(r.get("created_at") or ""),
                    ),
                )[0]
            else:
                free_rows = [r for r in matches if not r.get("itinerary_id")]
                row = free_rows[0] if free_rows else None
            if row is None:
'''
sub(old_sel, new_sel)

old_sync = '''        try:
            self._sync_wish_rows(session)
            self._sync_planned_rows(session)
        except Exception:
            logger.warning("plan: trip row sync failed", exc_info=True)
'''
new_sync = '''        try:
            self._sync_wish_rows(session)
            self._sync_planned_rows(session)
            # 2026-11-14（用户报「已排期里同一个心愿出现两三条」）：对账收尾
            # 顺手去重——同一行程里同名心愿行只留一行（已排期优先、最早建
            # 的留任），多余行软删留档自愈。
            hook = getattr(self._trip_items, "dedupe_itinerary_rows", None)
            if session.plan is not None and callable(hook):
                hook(session.plan.itinerary_id, actor=session.device_id)
        except Exception:
            logger.warning("plan: trip row sync failed", exc_info=True)
'''
sub(old_sync, new_sync)

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("plan patched")
