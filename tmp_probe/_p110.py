# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

# 1) PlanSession.wish_sources field
sub('''    avoid_sites: list[str] = Field(default_factory=list)
''', '''    avoid_sites: list[str] = Field(default_factory=list)
    # 心愿来源留档（2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」）：
    # 规划期间建的心愿不再落库——名字 → {source, note, city, dropped}，
    # 保存行程时 materialize_wish_rows 按它物化成正式行。
    wish_sources: dict[str, dict] = Field(default_factory=dict)
''')

# 2) _wish_draft_session -> always None
sub('''        新建行程要等用户点「💾 保存行程」才把心愿行转正；载入已存行程的
        改动（✏️ 修改）里，行程本身已经在库里，心愿单改动即时生效。
        返回会话号（草稿标记）或 None（已保存/编辑既有行程）。"""
        if session.source_itinerary_id or session.wish_committed:
            return None
        return session.session_id
''', '''        2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」：规划期间
        不再建草稿行（愿望走会话 wish_sources，保存物化）——恒 None。
        保留入口只为兼容既有调用。"""
        return None
''')

# 3) _record_link_sites -> session version
start = t.index("    def _record_link_sites(\n")
end = t.index("    async def _add_must_visits(\n")
new_block = NL.join([
'    def _record_link_sites(',
'        self,',
'        session: PlanSession,',
'        mandatory: list[str],',
'        url: str,',
'        kinds: dict[str, str] | None = None,',
'        origin: str = "link",',
'    ) -> None:',
'        """Product rule 2026-10-20: only the user-picked mandatory sites',
'        land in the trip-center wishlist. 2026-11-15 用户拍板「心愿单只在',
'        保存/删除时进数据库」：规划期间不再建行——来源/城市/备注先记在',
'        会话（wish_sources），保存行程时物化成正式行。"""',
'        kinds = kinds or {}',
'        source = "chat" if origin in ("brief", "image") else "paste"',
'        sources = dict(session.wish_sources or {})',
'        for site in mandatory:',
'            label = (',
'                L("必去·餐饮", "Must-visit · food")',
'                if kinds.get(site) == "food"',
'                else L("必去", "Must-visit")',
'            )',
'            city = session.site_cities.get(site) or (',
'                session.cities[0] if len(session.cities) == 1 else None',
'            )',
'            if origin == "image":',
'                note = L(',
'                    f"来自你发的图片（{label}）",',
'                    f"From your photo ({label})",',
'                )',
'            elif origin == "brief":',
'                note = L(',
'                    f"来自你的文字/视频描述（{label}）",',
'                    f"From your typed brief ({label})",',
'                )',
'            else:',
'                note = L(',
'                    f"来自链接 {url}（{label}）",',
'                    f"From a shared link {url} ({label})",',
'                )',
'            sources[site] = {"source": source, "note": note, "city": city}',
'            # §5.3：链接解析按 POI 聚合计数（小红书热度代理，只存统计）',
'            try:',
'                from app.services.poi_feedback import get_poi_feedback_store',
'',
'                get_poi_feedback_store().note_link_mention(site, city)',
'            except Exception:',
'                logger.warning("plan: note_link_mention failed", exc_info=True)',
'        session.wish_sources = sources',
'',
'',
])
t = t[:start] + new_block + t[end:]

# 4) _backfill_wish_city -> no-op
start = t.index("    def _backfill_wish_city(self, name: str, city: str) -> None:\n")
end = t.index("    async def _brief_site_round(\n")
new_block = NL.join([
'    def _backfill_wish_city(self, name: str, city: str) -> None:',
'        """心愿城市记录（2026-11-15 用户拍板「心愿单只在保存/删除时进',
'        数据库」）：规划期间不再写心愿行——城市随绑定/会话状态走',
'        （wish_bindings[name]["city"] / session.site_cities），保存行程',
'        物化成行时一并落库。保留入口只为兼容既有调用。""";',
'        return',
'',
'',
])
t = t[:start] + new_block + t[end:]

# 5) commit_wish_drafts rewrite + materialize
start = t.index("    def commit_wish_drafts(\n")
end = t.index("    def sync_trip_rows(self, session: PlanSession) -> None:\n")
new_block = NL.join([
'    def commit_wish_drafts(',
'        self, session: PlanSession, account: str | None = None',
'    ) -> int:',
'        """点「💾 保存行程」= 心愿单落库的唯一写时刻（2026-11-15 用户拍板',
'        「心愿单只在 保存新行程/保存修改/删除 时进数据库；规划期间不写库、',
'        不复制、不缓存」）：把会话里记下的心愿（must_visits / created_sites /',
'        wish_bindings / wish_sources / avoid_sites）按最终排期物化成',
'        trip_items 行，然后一次对账（翻已排期/回心愿单/去重）。返回落库行数。',
'        """',
'        if self._trip_items is None or session.plan is None:',
'            return 0',
'        committed = self.materialize_wish_rows(session, account=account)',
'        self.sync_trip_rows(session, at_save=True)',
'        session.wish_committed = True',
'        logger.info(',
'            "plan: wish rows materialized itinerary=%s rows=%s",',
'            session.plan.itinerary_id,',
'            committed,',
'        )',
'        return committed',
'',
'    def materialize_wish_rows(',
'        self, session: PlanSession, *, account: str | None = None',
'    ) -> int:',
'        """会话心愿 → trip_items 行（保存行程的时刻才写库）：按名字去重复用',
'        已存行；排进行程的翻 scheduled（note 已安排 + 规划字段），没排上的',
'        落心愿单（城市留档）；排除项（avoid_sites）打 EXCLUSION；城市不在',
'        本次行程的心愿落无行程心愿行。Best-effort。"""',
'        if self._trip_items is None or session.plan is None:',
'            return 0',
'        plan = session.plan',
'        itinerary_id = plan.itinerary_id',
'        account_id = account or getattr(session, "account_id", None)',
'        trip_cities = {',
'            _norm_city(c or "").removesuffix("市")',
'            for c in session.cities',
'            if (c or "").strip()',
'        }',
'        for day in plan.days:',
'            day_cities = {',
'                _norm_city(i.city or "").removesuffix("市")',
'                for i in day.items',
'                if isinstance(i, VisitItem) and (i.city or "").strip()',
'            }',
'            if day_cities:',
'                trip_cities |= day_cities',
'        names: list[str] = []',
'        for source in (',
'            session.must_visits,',
'            session.created_sites,',
'            list((session.wish_sources or {}).keys()),',
'            list((session.wish_bindings or {}).keys()),',
'        ):',
'            for name in source:',
'                if name and not any(_same_site(name, n) for n in names):',
'                    names.append(name)',
'        committed = 0',
'        for name in names:',
'            bound = (session.wish_bindings or {}).get(name) or self._wish_bindings.get(',
'                name',
'            )',
'            city = (',
'                session.site_cities.get(name)',
'                or str((bound or {}).get("city") or "").strip().removesuffix("市")',
'                or (session.wish_sources or {}).get(name, {}).get("city")',
'                or None',
'            )',
'            if city == "":',
'                city = None',
'            meta = (session.wish_sources or {}).get(name) or {}',
'            source = str(meta.get("source") or "chat")',
'            note = str(meta.get("note") or "") or L("来自聊天", "From chat")',
'            dropped = bool(meta.get("dropped"))',
'            target = None',
'            for day in plan.days:',
'                for item in day.items:',
'                    if not isinstance(item, VisitItem):',
'                        continue',
'                    if (',
'                        bound is not None',
'                        and item.poi_id',
'                        and item.poi_id == str(bound.get("source_poi_id") or "")',
'                    ):',
'                        target = item',
'                        break',
'                    # 名字命中即可（无 poi_id 的用户点名条目也要能对上）',
'                    if target is None and _name_dup(name, item.name):',
'                        target = item',
'                if target is not None:',
'                    break',
'            off_trip = bool(',
'                city and trip_cities and _norm_city(city).removesuffix("市") not in trip_cities',
'            )',
'            row = None',
'            try:',
'                row = self._trip_items.create(',
'                    name,',
'                    source=source,',
'                    # 保存行程 = 写库时刻：直接落正式行（无草稿）',
'                    itinerary_id=(None if off_trip else itinerary_id),',
'                    owner_device_id=session.device_id,',
'                    owner_account_id=account_id,',
'                    created_by=session.device_id,',
'                    city=city,',
'                    note=note,',
'                    poi_id=str((bound or {}).get("source_poi_id") or "") or None,',
'                    raw_command=name,',
'                    must_visit=(',
'                        name in (session.must_visits or []) and not dropped',
'                    ),',
'                )',
'                committed += 1',
'            except (InvalidSourceError, ValueError):',
'                logger.warning("plan: wish materialize create failed %s", name)',
'                continue',
'            if dropped:',
'                # 用户在追问轮撤掉的心愿：物化成 unwanted 行（心愿单移除留痕）',
'                try:',
'                    self._trip_items.update(',
'                        row["id"], status=STATUS_UNWANTED, note=note',
'                    )',
'                except Exception:',
'                    logger.warning(',
'                        "plan: wish materialize unwanted failed %s", name',
'                    )',
'                continue',
'            if off_trip or target is None or target.start_time is None:',
'                continue',
'            when = _wish_when_text(session, target)',
'            tail = L(',
'                f"已安排：{target.name}（第{target.day}天{when[0]}）",',
'                f"Scheduled: {target.name} (day {target.day}{when[1]})",',
'            )',
'            full_note = f"{note}｜{tail}" if note and note not in tail else tail',
'            try:',
'                self._trip_items.update(',
'                    row["id"],',
'                    status=STATUS_SCHEDULED,',
'                    day=target.day,',
'                    note=full_note,',
'                    **self._wish_row_plan_fields(session, target),',
'                )',
'            except Exception:',
'                logger.warning(',
'                    "plan: wish materialize schedule failed %s", name, exc_info=True',
'                )',
'        # 排除项（用户删掉的站点）：EXCLUSION 行（2026-11-13 拍板口径，',
'        # 落库时刻=保存行程）',
'        for name in session.avoid_sites or []:',
'            try:',
'                city = session.site_cities.get(name)',
'                self._trip_items.mark_excluded(',
'                    name,',
'                    itinerary_id=itinerary_id,',
'                    city=city,',
'                )',
'                committed += 1',
'            except (InvalidSourceError, ValueError):',
'                logger.warning("plan: exclusion materialize failed %s", name)',
'        return committed',
'',
'',
])
t = t[:start] + new_block + t[end:]

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("batch A ok")
