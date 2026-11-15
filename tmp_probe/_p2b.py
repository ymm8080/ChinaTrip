# -*- coding: utf-8 -*-
import io, os
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
text = io.open(p, encoding="utf-8", newline="").read()
orig = text

def sub(old, new, n=1):
    global text
    c = text.count(old)
    assert c == n, (c, old[:90])
    text = text.replace(old, new)

sub('''        must_visit: bool = False,\r
        raw_command: str | None = None,\r
        now: datetime | None = None,\r
    ) -> dict:\r
''', '''        must_visit: bool = False,\r
        raw_command: str | None = None,\r
        # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：规划会话\r
        # 建的行是草稿——只有点「💾 保存行程」才转正进心愿单\r
        draft_session_id: str | None = None,\r
        now: datetime | None = None,\r
    ) -> dict:\r
''')

sub('''            "id": uuid4().hex,\r
            "itinerary_id": itinerary_id,\r
''', '''            "id": uuid4().hex,\r
            "itinerary_id": itinerary_id,\r
            # 非空 = 草稿（未保存行程），看板/视图不返回（2026-11-14）\r
            "draft_session_id": draft_session_id,\r
''')

sub('''    def list_groups(\r
        self,\r
        itinerary_id: str | None = None,\r
        owner_device_id: str | None = None,\r
    ) -> dict:\r
''', '''    def list_groups(\r
        self,\r
        itinerary_id: str | None = None,\r
        owner_device_id: str | None = None,\r
        *,\r
        include_drafts: bool = True,\r
    ) -> dict:\r
''')
sub('''        items = list(self._items.values())\r
        if owner_device_id is not None:\r
''', '''        items = list(self._items.values())\r
        if not include_drafts:\r
            # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：草稿行\r
            # 只在规划引擎内部可见，看板/接口一律不返回\r
            items = [i for i in items if not i.get("draft_session_id")]\r
        if owner_device_id is not None:\r
''')

sub('''    def mark_excluded(\r
        self,\r
        name: str,\r
        *,\r
        itinerary_id: str | None = None,\r
        city: str | None = None,\r
    ) -> dict:\r
''', '''    def mark_excluded(\r
        self,\r
        name: str,\r
        *,\r
        itinerary_id: str | None = None,\r
        city: str | None = None,\r
        draft_session_id: str | None = None,\r
    ) -> dict:\r
''')
sub('''        created = self.create(\r
            name, source="plan_delete", itinerary_id=itinerary_id, city=city\r
        )\r
        return self.update(created["id"], status=STATUS_WISHLIST, exclusion_flag=True)\r
''', '''        created = self.create(\r
            name,\r
            source="plan_delete",\r
            itinerary_id=itinerary_id,\r
            city=city,\r
            draft_session_id=draft_session_id,\r
        )\r
        return self.update(created["id"], status=STATUS_WISHLIST, exclusion_flag=True)\r
''')

anchor = '''        # 兜底：仍挂着该行程的行（booked/unwanted 之外的异常态）一律解绑，\r
        # 否则 PG 外键会挡下行程删除（204 后行程复活）。\r
        for item in list(self._items.values()):\r
            if item.get("itinerary_id") == itinerary_id:\r
                self.unbind_itinerary(item["id"], now=now)\r
        return released\r
\r
'''
new_methods = anchor + '''    def commit_drafts(\r
        self,\r
        itinerary_id: str,\r
        session_id: str | None = None,\r
    ) -> int:\r
        """保存行程 = 心愿草稿转正（2026-11-14 用户拍板「没保存行程，心愿单\r
        就不该保存」）：本会话建的草稿行（以及已按名字挂到本行程的草稿行）\r
        清掉 draft_session_id、补上行程归属——从这一刻起看板/心愿单可见。\r
        返回转正行数。"""\r
        if not itinerary_id:\r
            return 0\r
        committed = 0\r
        hook = getattr(self, "_write_through", None)\r
        for item in list(self._items.values()):\r
            draft_sid = item.get("draft_session_id")\r
            if not draft_sid:\r
                continue\r
            if item.get("itinerary_id") != itinerary_id and draft_sid != session_id:\r
                continue\r
            item["draft_session_id"] = None\r
            if not item.get("itinerary_id"):\r
                item["itinerary_id"] = itinerary_id\r
            item["updated_at"] = _iso_now(None)\r
            committed += 1\r
            if callable(hook):\r
                hook(item["id"])\r
        if committed:\r
            logger.info(\r
                "trip_item_drafts_committed itinerary=%s session=%s rows=%d",\r
                itinerary_id,\r
                session_id,\r
                committed,\r
            )\r
        return committed\r
\r
    def purge_itinerary(\r
        self,\r
        itinerary_id: str,\r
        *,\r
        now: datetime | None = None,\r
        actor: str | None = None,\r
    ) -> list[dict]:\r
        """删行程 = 名下心愿单一并删除（2026-11-14 用户拍板：\r
        「当行程被用户删除时，它的相关心愿单没有被删除」）。\r
\r
        与旧 release_itinerary 的区别：不再把排期项重建回心愿单——心愿单\r
        随行程走，行程没了就一起走。booked 是真实订单（订单栏自有真相），\r
        只摘行程绑定、不删；其余状态（wishlist/scheduled/unwanted）一律\r
        软删留档（DELETION FLAG + 日期/时间/人）。返回被删的行。\r
\r
        PG 外键兜底同旧法：清完后仍挂着该行程的行一律解绑，否则 DELETE\r
        /itineraries/{id} 会被 FK 挡下（接口 204、刷新后又复活）。"""\r
        if not itinerary_id:\r
            return []\r
        rows = [\r
            dict(item)\r
            for item in self._items.values()\r
            if item.get("itinerary_id") == itinerary_id\r
        ]\r
        purged: list[dict] = []\r
        for item in rows:\r
            if item.get("status") == STATUS_BOOKED:\r
                self.unbind_itinerary(item["id"], now=now)\r
                continue\r
            try:\r
                self.delete(item["id"], actor=actor)\r
            except (InvalidTransitionError, NotFoundError):\r
                continue\r
            purged.append(item)\r
        for item in list(self._items.values()):\r
            if item.get("itinerary_id") == itinerary_id:\r
                self.unbind_itinerary(item["id"], now=now)\r
        logger.info(\r
            "trip_itinerary_purged itinerary=%s rows=%d actor=%s",\r
            itinerary_id,\r
            len(purged),\r
            actor,\r
        )\r
        return purged\r
\r
'''
sub(anchor, new_methods)

io.open(p, "w", encoding="utf-8", newline="").write(text)
print("trip_items patched", len(orig), "->", len(text))
