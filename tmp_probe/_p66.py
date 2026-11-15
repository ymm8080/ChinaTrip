# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

# 1) commit_drafts: rebind session rows to the saved trip unconditionally
sub('''            item["draft_session_id"] = None
            if not item.get("itinerary_id"):
                item["itinerary_id"] = itinerary_id
            # 转正即落 USER ID（登录账号）——看板按用户出内容
''', '''            item["draft_session_id"] = None
            # 2026-11-14 深夜（用户报「保存了行程，心愿不在已排期」）：会话
            # 中途重开过新行程时，行的 ref 还是旧草稿 id——转正一律重绑到
            # 本次保存的行程（这些行就是本会话许的愿）。
            item["itinerary_id"] = itinerary_id
            # 转正即落 USER ID（登录账号）——看板按用户出内容
''')

# 2) commit_orphan_drafts: adopt this user's orphan drafts at save
anchor = "    def purge_itinerary(\n"
if anchor not in t:
    anchor = "    def mark_excluded(\n"
new_method = NL.join([
'    def commit_orphan_drafts(',
'        self,',
'        itinerary_id: str,',
'        *,',
'        owner_device_id: str | None = None,',
'        owner_account_id: str | None = None,',
'        match_names: set[str] | None = None,',
'    ) -> int:',
'        """收编孤儿心愿草稿（2026-11-14 深夜，用户报「保存了行程，心愿',
'        却不在已排期」）：同一用户在多次规划/重开行程时聊出的心愿行挂着',
'        死掉的中途行程号（ref 不是任何已存行程）——保存本次行程时一并',
'        收编：名字命中本次行程点位的重绑到本行程（对账后进已排期），',
'        没命中的转正为无行程心愿行。别人的草稿、已存行程的行不动。',
'        返回收编行数。PG 侧靠读穿透保证内存是库内权威后再改。""";',
'        if not itinerary_id:',
'            return 0',
'        refresh = getattr(self, "_try_refresh", None)',
'        if callable(refresh):',
'            refresh()',
'        committed = 0',
'        for item in list(self._items.values()):',
'            if not item.get("draft_session_id") or item.get("deletion_flag"):',
'                continue',
'            if item.get("itinerary_id") == itinerary_id:',
'                continue  # 已挂本行程：commit_drafts 已处理',
'            row_dev = item.get("owner_device_id")',
'            row_acct = item.get("owner_account_id")',
'            if row_dev is not None or row_acct is not None:',
'                mine = (',
'                    (owner_device_id is not None and row_dev == owner_device_id)',
'                    or (owner_account_id is not None and row_acct == owner_account_id)',
'                )',
'                if not mine:',
'                    continue',
'            stored = self._items.get(item["id"])',
'            if stored is None:',
'                continue',
'            name = str(stored.get("name") or "")',
'            matched = match_names is None or any(',
'                _name_dup(name, n) for n in match_names',
'            )',
'            stored["draft_session_id"] = None',
'            if matched:',
'                stored["itinerary_id"] = itinerary_id',
'            stored["updated_at"] = _iso_now(None)',
'            self._persist(item["id"])',
'            committed += 1',
'            logger.info(',
'                "trip_orphan_draft_committed itinerary=%s name=%s matched=%s id=%s",',
'                itinerary_id,',
'                name,',
'                matched,',
'                item["id"],',
'            )',
'        return committed',
'',
'',
])
t = t.replace(anchor, new_method + anchor, 1)

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("service ok")
