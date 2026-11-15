# -*- coding: utf-8 -*-
import io, os
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
text = io.open(p, encoding="utf-8", newline="").read()
orig = text

def sub(old, new, n=1):
    global text
    c = text.count(old)
    assert c == n, (c, old[:100])
    text = text.replace(old, new)

# 1) PlanSession field
sub('''    source_itinerary_id: str | None = None\r
''', '''    source_itinerary_id: str | None = None\r
    # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：本会话是否已\r
    # 点过「💾 保存行程」——未保存前建的心愿行是草稿（draft_session_id），\r
    # 看板/心愿单不显示；保存时转正。from-itinerary 会话天然已保存。\r
    wish_committed: bool = False\r
''')

# 2) helper before _record_link_sites
sub('''    def _record_link_sites(\r
''', '''    def _wish_draft_session(self, session: PlanSession) -> str | None:\r
        """未保存行程的心愿行是会话草稿（2026-11-14 用户拍板：\r
        「WHEN I DO NOT SAVE TRIP, 心愿单 should not be saved」）。\r
\r
        新建行程要等用户点「💾 保存行程」才把心愿行转正；载入已存行程的\r
        改动（✏️ 修改）里，行程本身已经在库里，心愿单改动即时生效。\r
        返回会话号（草稿标记）或 None（已保存/编辑既有行程）。"""\r
        if session.source_itinerary_id or session.wish_committed:\r
            return None\r
        return session.session_id\r
\r
    def _record_link_sites(\r
''')

# 3) _record_link_sites create draft
sub('''                self._trip_items.create(\r
                    site,\r
                    source=source,\r
                    itinerary_id=itinerary_id,\r
                    owner_device_id=session.device_id,\r
                    city=city,\r
                    note=note,\r
                )\r
''', '''                self._trip_items.create(\r
                    site,\r
                    source=source,\r
                    itinerary_id=itinerary_id,\r
                    owner_device_id=session.device_id,\r
                    city=city,\r
                    note=note,\r
                    # 2026-11-14：未保存行程的心愿行是草稿（看板不显示）\r
                    draft_session_id=self._wish_draft_session(session),\r
                )\r
''')

# 4) sync_wishes_to_trip_items create draft
sub('''                    row = self._trip_items.create(\r
                        wish,\r
                        source="chat",\r
                        itinerary_id=itinerary_id,\r
                        owner_device_id=session.device_id,\r
                        note=L("来自聊天", "From chat"),\r
                        city=city,\r
''', '''                    row = self._trip_items.create(\r
                        wish,\r
                        source="chat",\r
                        itinerary_id=itinerary_id,\r
                        owner_device_id=session.device_id,\r
                        note=L("来自聊天", "From chat"),\r
                        city=city,\r
                        # 2026-11-14：未保存行程的心愿行是草稿（看板不显示）\r
                        draft_session_id=self._wish_draft_session(session),\r
''')

# 5) sync_removals_to_trip_items: draft arg
sub('''    def sync_removals_to_trip_items(\r
        self, plan_before: ItineraryPlan, diffs: list[DiffOp]\r
    ) -> None:\r
''', '''    def sync_removals_to_trip_items(\r
        self,\r
        plan_before: ItineraryPlan,\r
        diffs: list[DiffOp],\r
        *,\r
        draft_session_id: str | None = None,\r
    ) -> None:\r
''')
sub('''                self._trip_items.mark_excluded(\r
                    item.name,\r
                    itinerary_id=plan_before.itinerary_id,\r
                    city=item.city,\r
                )\r
''', '''                self._trip_items.mark_excluded(\r
                    item.name,\r
                    itinerary_id=plan_before.itinerary_id,\r
                    city=item.city,\r
                    draft_session_id=draft_session_id,\r
                )\r
''')
sub('''            if any(op.op == "remove" for op in diffs):\r
                self.sync_removals_to_trip_items(plan_before, diffs)\r
''', '''            if any(op.op == "remove" for op in diffs):\r
                self.sync_removals_to_trip_items(\r
                    plan_before, diffs, draft_session_id=self._wish_draft_session(session)\r
                )\r
''')

# 6) commit_wish_drafts next to sync_trip_rows
sub('''    def sync_trip_rows(self, session: PlanSession) -> None:\r
''', '''    def commit_wish_drafts(self, session: PlanSession) -> int:\r
        """点「💾 保存行程」= 本会话心愿行转正（2026-11-14 用户拍板\r
        「WHEN I DO NOT SAVE TRIP, 心愿单 should not be saved」的对偶：\r
        保存了就该进心愿单）。清掉 draft_session_id 后看板即可见；\r
        之后再聊出来的心愿行也直接是正式行（行程已在库）。"""\r
        if self._trip_items is None or session.plan is None:\r
            return 0\r
        itinerary_id = session.plan.itinerary_id\r
        hook = getattr(self._trip_items, "commit_drafts", None)\r
        committed = hook(itinerary_id, session.session_id) if callable(hook) else 0\r
        session.wish_committed = True\r
        logger.info(\r
            "plan: wish drafts committed itinerary=%s rows=%s",\r
            itinerary_id,\r
            committed,\r
        )\r
        return int(committed or 0)\r
\r
    def sync_trip_rows(self, session: PlanSession) -> None:\r
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(text)
print("plan patched", len(orig), "->", len(text))
