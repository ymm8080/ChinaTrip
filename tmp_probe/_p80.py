# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

# 1) commit_wish_drafts -> save-time materialization + one-shot reconcile
start = t.index("    def commit_wish_drafts(\n")
end = t.index("    def sync_trip_rows(self, session: PlanSession) -> None:\n")
new_block = '''    def commit_wish_drafts(
        self, session: PlanSession, account: str | None = None
    ) -> int:
        """点「💾 保存行程」= 心愿单落库的唯一写时刻（2026-11-15 用户拍板
        「心愿单只在 保存新行程/保存修改/删除 时进数据库；规划期间不写库、
        不复制、不缓存」）：把会话里记下的心愿（must_visits / created_sites /
        wish_bindings / wish_sources / avoid_sites）按最终排期物化成
        trip_items 行，然后一次对账（翻已排期/回心愿单/去重）。返回落库行数。
        """
        if self._trip_items is None or session.plan is None:
            return 0
        committed = self.materialize_wish_rows(session, account=account)
        self.sync_trip_rows(session, at_save=True)
        session.wish_committed = True
        session.wish_drafts = {}
        logger.info(
            "plan: wish rows materialized itinerary=%s rows=%s",
            session.plan.itinerary_id,
            committed,
        )
        return committed

    def materialize_wish_rows(
        self, session: PlanSession, *, account: str | None = None
    ) -> int:
        """会话心愿 → trip_items 行（保存行程的时刻才写库）：按名字去重复用
        已存行；排进行程的翻 scheduled（note 已安排 + 规划字段），没排上的
        落心愿单（城市留档）；排除项（avoid_sites）打 EXCLUSION；城市不在
        本次行程的心愿落无行程心愿行。Best-effort。"""
        if self._trip_items is None or session.plan is None:
            return 0
        plan = session.plan
        itinerary_id = plan.itinerary_id
        account_id = account or getattr(session, "account_id", None)
        trip_cities = {
            _norm_city(c or "").removesuffix("市")
            for c in session.cities
            if (c or "").strip()
        }
        for day in plan.days:
            day_cities = {
                _norm_city(i.city or "").removesuffix("市")
                for i in day.items
                if isinstance(i, VisitItem) and (i.city or "").strip()
            }
            if day_cities:
                trip_cities |= day_cities
        names: list[str] = []
        for source in (
            session.must_visits,
            session.created_sites,
            list((session.wish_sources or {}).keys()),
            list((session.wish_bindings or {}).keys()),
        ):
            for name in source:
                if name and not any(_same_site(name, n) for n in names):
                    names.append(name)
        committed = 0
        for name in names:
            bound = (session.wish_bindings or {}).get(name) or self._wish_bindings.get(
                name
            )
            city = (
                session.site_cities.get(name)
                or str((bound or {}).get("city") or "").strip().removesuffix("市")
                or (session.wish_sources or {}).get(name, {}).get("city")
                or None
            )
            if city == "":
                city = None
            meta = (session.wish_sources or {}).get(name) or {}
            source = str(meta.get("source") or "chat")
            note = str(meta.get("note") or "") or L("来自聊天", "From chat")
            target = None
            for day in plan.days:
                for item in day.items:
                    if not isinstance(item, VisitItem):
                        continue
                    if (
                        bound is not None
                        and item.poi_id
                        and item.poi_id == str(bound.get("source_poi_id") or "")
                    ):
                        target = item
                        break
                    if target is None and item.poi_id and _name_dup(name, item.name):
                        target = item
                if target is not None:
                    break
            off_trip = bool(
                city and trip_cities and _norm_city(city).removesuffix("市") not in trip_cities
            )
            row = None
            try:
                row = self._trip_items.create(
                    name,
                    source=source,
                    # 保存行程 = 写库时刻：直接落正式行（无草稿）
                    itinerary_id=(None if off_trip else itinerary_id),
                    owner_device_id=session.device_id,
                    owner_account_id=account_id,
                    created_by=session.device_id,
                    city=city,
                    note=note,
                    poi_id=str((bound or {}).get("source_poi_id") or "") or None,
                    raw_command=name,
                    must_visit=name in (session.must_visits or []),
                )
                committed += 1
            except (InvalidSourceError, ValueError):
                logger.warning("plan: wish materialize create failed %s", name)
                continue
            if off_trip or target is None or target.start_time is None:
                continue
            when = _wish_when_text(session, target)
            tail = L(
                f"已安排：{target.name}（第{target.day}天{when[0]}）",
                f"Scheduled: {target.name} (day {target.day}{when[1]})",
            )
            full_note = f"{note}｜{tail}" if note and note not in tail else tail
            try:
                self._trip_items.update(
                    row["id"],
                    status=STATUS_SCHEDULED,
                    day=target.day,
                    note=full_note,
                    **self._wish_row_plan_fields(session, target),
                )
            except Exception:
                logger.warning(
                    "plan: wish materialize schedule failed %s", name, exc_info=True
                )
        # 排除项（用户删掉的站点）：EXCLUSION 行（2026-11-13 拍板口径，
        # 落库时刻=保存行程）
        for name in session.avoid_sites or []:
            try:
                city = session.site_cities.get(name)
                self._trip_items.mark_excluded(
                    name,
                    itinerary_id=itinerary_id,
                    city=city,
                )
                committed += 1
            except (InvalidSourceError, ValueError):
                logger.warning("plan: exclusion materialize failed %s", name)
        return committed

'''
t = t[:start] + new_block + t[end:]

# 2) sync_trip_rows: at_save gate
sub('''    def sync_trip_rows(self, session: PlanSession) -> None:
        """行程↔看板对账入口（2026-11-13 用户报「陕历博在行程里被安排，却没从
        心愿单翻到已排期」）：打开/保存/载入行程都跑一遍——心愿单里已被本行程
        落排的点翻已排期，已排期里本行程已经没有的点回心愿单。Best-effort，
        绝不阻塞请求。"""
        try:
''', '''    def sync_trip_rows(self, session: PlanSession, *, at_save: bool = False) -> None:
        """行程↔看板对账（2026-11-15 用户拍板「心愿单只在 保存新行程/保存
        修改/删除 时进数据库」）：只在保存行程时对账——规划回合内不再写
        心愿行（不落库、不复制、不缓存），看板保持「最后一次保存」的状态。
        Best-effort，绝不阻塞请求。"""
        if not at_save:
            return
        try:
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("core ok")
