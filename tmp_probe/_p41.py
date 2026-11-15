# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''        duplicate = self._find_duplicate(
            name,
            source=source,
            itinerary_id=itinerary_id,
            city=city,
            poi_id=poi_id,
            owner_device_id=owner_device_id,
            items=known,
        )
''', '''        duplicate = self._find_duplicate(
            name,
            source=source,
            itinerary_id=itinerary_id,
            city=city,
            poi_id=poi_id,
            owner_device_id=owner_device_id,
            owner_account_id=owner_account_id,
            items=known,
        )
''')

sub('''        items: Iterable[dict] | None = None,
        owner_device_id: str | None = None,
    ) -> dict | None:
''', '''        items: Iterable[dict] | None = None,
        owner_device_id: str | None = None,
        owner_account_id: str | None = None,
    ) -> dict | None:
''')

# mark_excluded: owner_account_id passthrough
sub('''    def mark_excluded(
        self,
        name: str,
        *,
        itinerary_id: str | None = None,
        city: str | None = None,
        draft_session_id: str | None = None,
    ) -> dict:
''', '''    def mark_excluded(
        self,
        name: str,
        *,
        itinerary_id: str | None = None,
        city: str | None = None,
        draft_session_id: str | None = None,
        owner_account_id: str | None = None,
    ) -> dict:
''')
sub('''        created = self.create(
            name,
            source="plan_delete",
            itinerary_id=itinerary_id,
            city=city,
            draft_session_id=draft_session_id,
        )
''', '''        created = self.create(
            name,
            source="plan_delete",
            itinerary_id=itinerary_id,
            city=city,
            draft_session_id=draft_session_id,
            owner_account_id=owner_account_id,
        )
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")

# pg_state.py
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()

sub('''        "draft_session_id": (item.get("draft_session_id") or None),
        "owner_device_id": (item.get("owner_device_id") or None),
''', '''        "draft_session_id": (item.get("draft_session_id") or None),
        # 2026-11-14（用户拍板「心愿单也是 USER ID 的数据」）：登录账号列
        "owner_account_id": (item.get("owner_account_id") or None),
        "owner_device_id": (item.get("owner_device_id") or None),
''')

sub('''                    "owner_device_id",
                    "itinerary_ref",
                    "draft_session_id",
                ):
''', '''                    "owner_device_id",
                    "itinerary_ref",
                    "draft_session_id",
                    "owner_account_id",
                ):
''')

sub('''    def list_groups(
        self,
        itinerary_id: str | None = None,
        owner_device_id: str | None = None,
        *,
        include_drafts: bool = True,
    ) -> dict:
        # 读穿透（PG 读权威）：看板/规划收口每次回库取新，跨进程排期立即可见。
        self._try_refresh()
        return super().list_groups(
            itinerary_id, owner_device_id, include_drafts=include_drafts
        )
''', '''    def list_groups(
        self,
        itinerary_id: str | None = None,
        owner_device_id: str | None = None,
        owner_account_id: str | None = None,
        *,
        include_drafts: bool = True,
    ) -> dict:
        # 读穿透（PG 读权威）：看板/规划收口每次回库取新，跨进程排期立即可见。
        self._try_refresh()
        return super().list_groups(
            itinerary_id,
            owner_device_id,
            owner_account_id,
            include_drafts=include_drafts,
        )
''')

# commit_drafts override: accept + stamp account in SQL
sub('''    def commit_drafts(
        self,
        itinerary_id: str,
        session_id: str | None = None,
    ) -> int:
''', '''    def commit_drafts(
        self,
        itinerary_id: str,
        session_id: str | None = None,
        owner_account_id: str | None = None,
    ) -> int:
''')
sub('''        committed = super().commit_drafts(itinerary_id, session_id)
''', '''        committed = super().commit_drafts(itinerary_id, session_id, owner_account_id)
''')
sub('''                        "UPDATE trip_items t"
                        " SET draft_session_id = NULL,"
                        " itinerary_ref = COALESCE(t.itinerary_ref, :ref),"
''', '''                        "UPDATE trip_items t"
                        " SET draft_session_id = NULL,"
                        " owner_account_id = COALESCE(t.owner_account_id, :acct),"
                        " itinerary_ref = COALESCE(t.itinerary_ref, :ref),"
''')
sub('''                    {"ref": itinerary_id, "sid": session_id or ""},
''', '''                    {
                        "ref": itinerary_id,
                        "sid": session_id or "",
                        "acct": owner_account_id or "",
                    },
''')

# _db_find_duplicate: pass account into predicate
sub('''            owner_device_id=kwargs.get("owner_device_id"),
''', '''            owner_device_id=kwargs.get("owner_device_id"),
            owner_account_id=kwargs.get("owner_account_id"),
''')

io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("pg_state ok")
