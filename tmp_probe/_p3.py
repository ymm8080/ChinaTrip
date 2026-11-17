# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
text = io.open(p, encoding="utf-8", newline="").read()
orig = text

def sub(old, new, n=1):
    global text
    c = text.count(old)
    assert c == n, (c, old[:90])
    text = text.replace(old, new)

# 1) projection
sub('''        "itinerary_ref": (item.get("itinerary_id") or None),\r
        "owner_device_id": (item.get("owner_device_id") or None),\r
''', '''        "itinerary_ref": (item.get("itinerary_id") or None),\r
        # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：会话草稿\r
        # 标记进列，看板/心愿单视图过滤；保存行程时清空转正\r
        "draft_session_id": (item.get("draft_session_id") or None),\r
        "owner_device_id": (item.get("owner_device_id") or None),\r
''')

# 2) reload: backfill from row
sub('''                    "owner_device_id",\r
                    "itinerary_ref",\r
                ):\r
''', '''                    "owner_device_id",\r
                    "itinerary_ref",\r
                    "draft_session_id",\r
                ):\r
''')

# 3) list_groups override
sub('''    def list_groups(\r
        self,\r
        itinerary_id: str | None = None,\r
        owner_device_id: str | None = None,\r
    ) -> dict:\r
        # 读穿透（PG 读权威）：看板/规划收口每次回库取新，跨进程排期立即可见。\r
        self._try_refresh()\r
        return super().list_groups(itinerary_id, owner_device_id)\r
''', '''    def list_groups(\r
        self,\r
        itinerary_id: str | None = None,\r
        owner_device_id: str | None = None,\r
        *,\r
        include_drafts: bool = True,\r
    ) -> dict:\r
        # 读穿透（PG 读权威）：看板/规划收口每次回库取新，跨进程排期立即可见。\r
        self._try_refresh()\r
        return super().list_groups(\r
            itinerary_id, owner_device_id, include_drafts=include_drafts\r
        )\r
''')

# 4) duplicate query: own-session drafts only
sub('''        rows = session.execute(\r
            text(\r
                "SELECT payload FROM trip_items"\r
                " WHERE status <> 'unwanted' AND deletion_flag = false"\r
                " ORDER BY created_at ASC NULLS LAST"\r
            )\r
        ).all()\r
''', '''        # 2026-11-14：草稿行只在本会话内参与查重——别的未保存会话留下的\r
        # 草稿不能把新会话的心愿「吸」成一条看不见的行（本会话重说一遍\r
        # 仍要命中自己的草稿，防重复建行）。\r
        rows = session.execute(\r
            text(\r
                "SELECT payload FROM trip_items"\r
                " WHERE status <> 'unwanted' AND deletion_flag = false"\r
                " AND (draft_session_id IS NULL OR draft_session_id = :draft_sid)"\r
                " ORDER BY created_at ASC NULLS LAST"\r
            ),\r
            {"draft_sid": kwargs.get("draft_session_id") or ""},\r
        ).all()\r
''')

# 5) overrides after release_itinerary
anchor = '''    def delete(self, item_id: str, *, actor: str | None = None) -> None:\r
        """删除 = 软删（2026-11-13 用户拍板「心愿单也是数据库」）：行保留，\r
'''
new = '''    def commit_drafts(\r
        self,\r
        itinerary_id: str,\r
        session_id: str | None = None,\r
    ) -> int:\r
        """保存行程 = 心愿草稿转正（2026-11-14）。跨进程兜底：本进程内存里\r
        可能没有另一端口建的草稿行，先按 SQL 清标记（payload 同源），再\r
        回灌内存；FK 列只在行程确实存在时补。"""\r
        committed = super().commit_drafts(itinerary_id, session_id)\r
        if not (self._pg_ok and itinerary_id):\r
            return committed\r
        uid = _pg_uuid_loose(itinerary_id, "it_")\r
        try:\r
            with self._session_factory() as session, session.begin():\r
                result = session.execute(\r
                    text(\r
                        "UPDATE trip_items t"\r
                        " SET draft_session_id = NULL,"\r
                        " itinerary_ref = COALESCE(t.itinerary_ref, :ref),"\r
                        " payload = (COALESCE(t.payload, '{}'::jsonb)"\r
                        "   - 'draft_session_id')"\r
                        "   || jsonb_build_object("\r
                        "        'itinerary_id',"\r
                        "        COALESCE(t.payload->>'itinerary_id', :ref))"\r
                        " WHERE t.draft_session_id IS NOT NULL"\r
                        "   AND (t.draft_session_id = :sid OR t.itinerary_ref = :ref)"\r
                    ),\r
                    {"ref": itinerary_id, "sid": session_id or "", "uid": uid},\r
                )\r
                rowcount = getattr(result, "rowcount", None)\r
                if rowcount:\r
                    committed += int(rowcount)\r
                if uid is not None:\r
                    session.execute(\r
                        text(\r
                            "UPDATE trip_items SET itinerary_id = :uid"\r
                            " WHERE itinerary_ref = :ref AND itinerary_id IS NULL"\r
                            "   AND EXISTS (SELECT 1 FROM itineraries i"\r
                            "                WHERE i.id = :uid)"\r
                        ),\r
                        {"uid": uid, "ref": itinerary_id},\r
                    )\r
            self._pg_reload_items()\r
        except Exception:\r
            logger.warning(\r
                "pg_state: 心愿草稿转正失败 itinerary=%s", itinerary_id, exc_info=True\r
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
        """删行程 = 名下心愿单一并删除（2026-11-14）。跨进程兜底：本进程\r
        内存里没有该行程的行时先回库取权威，否则漏删的行会在删行程后\r
        继续挂在死行程上（看板又冒出来）。"""\r
        if (\r
            self._pg_ok\r
            and itinerary_id\r
            and not any(\r
                it.get("itinerary_id") == itinerary_id for it in self._items.values()\r
            )\r
        ):\r
            self._try_refresh()\r
        return super().purge_itinerary(itinerary_id, now=now, actor=actor)\r
\r
'''
sub(anchor, new + anchor)

io.open(p, "w", encoding="utf-8", newline="").write(text)
print("pg_state patched", len(orig), "->", len(text))
