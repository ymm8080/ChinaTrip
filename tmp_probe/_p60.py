# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

start = t.index("    def release_itinerary(\n")
end = t.index("    def commit_drafts(\n")
new_method = NL.join([
'    def release_itinerary(',
'        self,',
'        itinerary_id: str,',
'        *,',
'        now: datetime | None = None,',
'        actor: str | None = None,',
'    ) -> list[dict]:',
'        """行程被手工删除（2026-11-14 二拍，覆盖同日早些的「一并删除」口径）：',
'        名下心愿行不删——TRIP ID 清空（itinerary_ref/payload 同源清空，',
'        wish_items 视图的 trip_id 随之空白），排期项退回心愿单栏（day/',
'        position/booking_id 清空、note 剥「已安排」尾段、ARRANGED 取消），',
'        心愿单/不想去行只摘绑定原地保留，本会话草稿行转正为无行程心愿行。',
'        booked 是真实订单（订单栏自有真相），只摘绑定不删。返回被释放的行。',
'',
'        兜底：清完后仍挂着该行程的行一律解绑，否则 PG 外键会挡下行程删除',
'        （接口 204 后行程复活）。释放后的行回到「无行程心愿行」，之后被',
'        新行程落排时按名字重新认领挂靠。""";',
'        if not itinerary_id:',
'            return []',
'        bound = [',
'            dict(item)',
'            for item in self._items.values()',
'            if item.get("itinerary_id") == itinerary_id',
'        ]',
'        released: list[dict] = []',
'        for item in bound:',
'            item_id = item["id"]',
'            status = item.get("status")',
'            if status == STATUS_BOOKED:',
'                # 真实订单不退回：只摘行程绑定（订单栏自有真相）',
'                self.unbind_itinerary(item_id, now=now)',
'                continue',
'            # 草稿行转正：行程没了，「保存行程」不会再发生——按用户口径',
'            # 退回心愿单（清 draft 标记 + 摘行程绑定）',
'            if item.get("draft_session_id"):',
'                item["draft_session_id"] = None',
'                self._persist(item_id)',
'            try:',
'                if status == STATUS_SCHEDULED:',
'                    # 排期项回心愿单：状态机清 day/position/booking_id/',
'                    # planned_date/start_time/end_time，ARRANGED 取消；',
'                    # note 剥「已安排」尾段，心愿单不再声称已安排',
'                    raw_note = str(item.get("note") or "")',
'                    base = strip_scheduled_note(raw_note)',
'                    kwargs: dict = {}',
'                    if base != raw_note:',
'                        kwargs["note"] = base',
'                    released.append(',
'                        self.update(item_id, status=STATUS_WISHLIST, **kwargs)',
'                    )',
'                else:',
'                    # 心愿单/不想去行：原地保留，只摘行程绑定',
'                    released.append(',
'                        dict(self.unbind_itinerary(item_id, now=now) or item)',
'                    )',
'            except (InvalidTransitionError, NotFoundError):',
'                continue',
'        # 兜底：仍挂着该行程的行（booked/unwanted 之外的异常态）一律解绑，',
'        # 否则 PG 外键会挡下行程删除（204 后行程复活）。',
'        for item in list(self._items.values()):',
'            if item.get("itinerary_id") == itinerary_id:',
'                self.unbind_itinerary(item["id"], now=now)',
'        logger.info(',
'            "trip_itinerary_released itinerary=%s rows=%d actor=%s",',
'            itinerary_id,',
'            len(released),',
'            actor,',
'        )',
'        return released',
'',
'',
])
t = t[:start] + new_method + t[end:]

# drop purge_itinerary (base)
ps = t.index("    def purge_itinerary(\n")
pe = t.index("    def mark_excluded(\n")
t = t[:ps] + t[pe:]

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("trip_items release rewritten")

# pg_state: drop purge override
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()
ps2 = t2.index("    def purge_itinerary(\n")
pe2 = t2.index("    def delete(self, item_id: str, *, actor: str | None = None) -> None:\n")
t2 = t2[:ps2] + t2[pe2:]
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("pg_state purge override dropped")
