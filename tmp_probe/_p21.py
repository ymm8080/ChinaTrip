# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:110])
    t = t.replace(old, new)

# import _wish_key
sub('''from app.services.trip_items import (\r
    STATUS_BOOKED,\r
    STATUS_SCHEDULED,\r
    STATUS_UNWANTED,\r
    STATUS_WISHLIST,\r
    strip_scheduled_note,\r
)\r
''', '''from app.services.trip_items import (\r
    STATUS_BOOKED,\r
    STATUS_SCHEDULED,\r
    STATUS_UNWANTED,\r
    STATUS_WISHLIST,\r
    _wish_key,\r
    strip_scheduled_note,\r
)\r
''')

# ---- _sync_wish_rows loop head rewrite ----
old_head = '''        rows = groups.get("wishlist", []) + groups.get("scheduled", [])\r
        for it in rows:\r
            # 2026-10-30 深夜：行按名字全局去重（跨会话共享）——凡命中本会\r
            # 话心愿名的行即本用户当前心愿行，无条件换绑当前行程；旧 id 记\r
            # 入 linked_itins 供追溯。\r
            name = str(it.get("name") or "")\r
            if not name or not any(_name_dup(name, n) for n in names):\r
                continue\r
            # 2026-11-13（用户拍板「心愿单的城市必须在插入的时候就标注\r
            # 城市」+ 陕历博串行程案）：行城是权威——已定城且不在本次\r
            # 行程的，不换绑、不翻已排期（旧行为按名字无条件 force 换绑，\r
            # 西安心愿被挂到成都重庆行程上）。\r
            row_city = _norm_city(str(it.get("city") or "")).removesuffix("市")\r
            # 2026-11-13（用户报「已排期里都是上海行程，可是行程根本没有\r
            # 上海」）：城闸以**行程真正有落点的城**为准——逐日看条目城，某天\r
            # 一条带城的都没有才回退 base_city；全程住西安的 上海→西安→上海\r
            # 行程不再把上海心愿吸收进来（cities 只是路线端点）。\r
            trip_cities_here: set[str] = set()\r
            for day in session.plan.days:\r
                day_cities = {\r
                    _norm_city(i.city or "").removesuffix("市")\r
                    for i in day.items\r
                    if isinstance(i, VisitItem) and (i.city or "").strip()\r
                }\r
                if not day_cities and (day.base_city or "").strip():\r
                    day_cities = {\r
                        _norm_city(day.base_city or "").removesuffix("市")\r
                    }\r
                trip_cities_here |= day_cities\r
            if not trip_cities_here:\r
                trip_cities_here = {\r
                    _norm_city(c or "").removesuffix("市")\r
                    for c in session.cities\r
                    if (c or "").strip()\r
                }\r
            if row_city and trip_cities_here and row_city not in trip_cities_here:\r
                logger.info(\r
                    "plan: wish row off-trip skip %s city=%s trip_cities=%s",\r
                    name,\r
                    row_city,\r
                    session.cities,\r
                )\r
                continue\r
            row_itin = it.get("itinerary_id")\r
'''
new_head = '''        rows = groups.get("wishlist", []) + groups.get("scheduled", [])\r
        # 2026-11-13（用户报「已排期里都是上海行程…」）：城闸以**行程真正\r
        # 有落点的城**为准——逐日看条目城，某天一条带城的都没有才回退\r
        # base_city；全程住西安的 上海→西安→上海 行程不再把上海心愿吸收\r
        # 进来（cities 只是路线端点）。行级判定共用，只算一次。\r
        trip_cities_here: set[str] = set()\r
        for day in session.plan.days:\r
            day_cities = {\r
                _norm_city(i.city or "").removesuffix("市")\r
                for i in day.items\r
                if isinstance(i, VisitItem) and (i.city or "").strip()\r
            }\r
            if not day_cities and (day.base_city or "").strip():\r
                day_cities = {_norm_city(day.base_city or "").removesuffix("市")}\r
            trip_cities_here |= day_cities\r
        if not trip_cities_here:\r
            trip_cities_here = {\r
                _norm_city(c or "").removesuffix("市")\r
                for c in session.cities\r
                if (c or "").strip()\r
            }\r
        cur_sid = self._wish_draft_session(session)\r
\r
        def _wish_row_eligible(row: dict) -> bool:\r
            """2026-11-14（用户报「已排期里同一个心愿出现两三条」）认领闸：\r
            名字命中 + 城市在行程内 + 不是别的会话的草稿 + 不是别的行程的行。\r
            旧行为按名字跨会话/跨行程无条件吸收——重新规划每开一局就新建\r
            一行再全量挂进来，已排期于是同一心愿越滚越多。"""\r
            name = str(row.get("name") or "")\r
            if not name or not any(_name_dup(name, n) for n in names):\r
                return False\r
            row_city = _norm_city(str(row.get("city") or "")).removesuffix("市")\r
            if row_city and trip_cities_here and row_city not in trip_cities_here:\r
                logger.info(\r
                    "plan: wish row off-trip skip %s city=%s trip_cities=%s",\r
                    name,\r
                    row_city,\r
                    session.cities,\r
                )\r
                return False\r
            row_draft = str(row.get("draft_session_id") or "")\r
            if row_draft and row_draft != (cur_sid or ""):\r
                return False\r
            row_itin = row.get("itinerary_id")\r
            if row_itin and row_itin != itin:\r
                return False\r
            return True\r
\r
        bound_rows: list[dict] = []\r
        free_rows: list[dict] = []\r
        for it in rows:\r
            if _wish_row_eligible(it):\r
                (bound_rows if it.get("itinerary_id") == itin else free_rows).append(it)\r
        # 每个心愿名只认领一行：已挂本行程的优先（已排期且最早建的留任），\r
        # 其次无绑定正式行；同名多行挂在本行程 = 历史重复，软删自愈。\r
        picked_rows: list[dict] = []\r
        seen_keys: set[str] = set()\r
        drop_rows: list[dict] = []\r
        for it in sorted(\r
            bound_rows,\r
            key=lambda r: (\r
                r.get("status") != STATUS_SCHEDULED,\r
                str(r.get("created_at") or ""),\r
            ),\r
        ):\r
            key = _wish_key(str(it.get("name") or ""))\r
            if key in seen_keys:\r
                drop_rows.append(it)\r
            else:\r
                seen_keys.add(key)\r
                picked_rows.append(it)\r
        for it in free_rows:\r
            key = _wish_key(str(it.get("name") or ""))\r
            if key not in seen_keys:\r
                seen_keys.add(key)\r
                picked_rows.append(it)\r
        for extra in drop_rows:\r
            try:\r
                self._trip_items.delete(extra["id"], actor=session.device_id)\r
                logger.info(\r
                    "plan: duplicate wish row dropped %s id=%s",\r
                    extra.get("name"),\r
                    extra["id"],\r
                )\r
            except Exception:\r
                logger.warning(\r
                    "plan: duplicate wish row drop failed id=%s",\r
                    extra.get("id"),\r
                    exc_info=True,\r
                )\r
        for it in picked_rows:\r
            name = str(it.get("name") or "")\r
            row_itin = it.get("itinerary_id")\r
'''
sub(old_head, new_head)

# ---- _sync_planned_rows selection rewrite ----
old_sel = '''        rows = [r for g in groups.values() for r in g]\r
        for item in planned:\r
            row = next(\r
                (\r
                    r\r
                    for r in rows\r
                    if (item.poi_id and r.get("poi_id") and r["poi_id"] == item.poi_id)\r
                    or _name_dup(str(r.get("name") or ""), item.name)\r
                ),\r
                None,\r
            )\r
            if row is None:\r
'''
new_sel = '''        rows = [r for g in groups.values() for r in g]\r
        cur_sid = self._wish_draft_session(session)\r
        for item in planned:\r
            matches = [\r
                r\r
                for r in rows\r
                if (item.poi_id and r.get("poi_id") and r["poi_id"] == item.poi_id)\r
                or _name_dup(str(r.get("name") or ""), item.name)\r
            ]\r
            # 2026-11-14：别会话草稿/别行程的行不认领；已挂本行程的行优先，\r
            # 其次无绑定行——防同一心愿的多行被轮流翻牌成已排期。\r
            matches = [\r
                r\r
                for r in matches\r
                if not str(r.get("draft_session_id") or "")\r
                or str(r.get("draft_session_id")) == (cur_sid or "")\r
            ]\r
            bound_rows = [r for r in matches if r.get("itinerary_id") == itin]\r
            if bound_rows:\r
                row = sorted(\r
                    bound_rows,\r
                    key=lambda r: (\r
                        r.get("status") != STATUS_SCHEDULED,\r
                        str(r.get("created_at") or ""),\r
                    ),\r
                )[0]\r
            else:\r
                free_rows = [r for r in matches if not r.get("itinerary_id")]\r
                row = free_rows[0] if free_rows else None\r
            if row is None:\r
'''
sub(old_sel, new_sel)

# ---- sync_trip_rows: dedupe call ----
old_sync = '''        try:\r
            self._sync_wish_rows(session)\r
            self._sync_planned_rows(session)\r
        except Exception:\r
            logger.warning("plan: trip row sync failed", exc_info=True)\r
'''
new_sync = '''        try:\r
            self._sync_wish_rows(session)\r
            self._sync_planned_rows(session)\r
            # 2026-11-14（用户报「已排期里同一个心愿出现两三条」）：对账收尾\r
            # 顺手去重——同一行程里同名心愿行只留一行（已排期优先、最早建\r
            # 的留任），多余行软删留档自愈。\r
            hook = getattr(self._trip_items, "dedupe_itinerary_rows", None)\r
            if session.plan is not None and callable(hook):\r
                hook(session.plan.itinerary_id, actor=session.device_id)\r
        except Exception:\r
            logger.warning("plan: trip row sync failed", exc_info=True)\r
'''
sub(old_sync, new_sync)

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("plan patched")
