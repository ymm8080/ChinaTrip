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

# 1) create: owner_account_id param + item field
sub('''        # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：规划会话
        # 建的行是草稿——只有点「💾 保存行程」才转正进心愿单
        draft_session_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
''', '''        # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：规划会话
        # 建的行是草稿——只有点「💾 保存行程」才转正进心愿单
        draft_session_id: str | None = None,
        # 2026-11-14（用户拍板「心愿单/已排期也是 USER ID 的数据」）：登录
        # 账号随行落库——打开看板按用户出内容，换设备登录也能看到
        owner_account_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
''')
sub('''            # 非空 = 草稿（未保存行程），看板/视图不返回（2026-11-14）
            "draft_session_id": draft_session_id,
''', '''            # 非空 = 草稿（未保存行程），看板/视图不返回（2026-11-14）
            "draft_session_id": draft_session_id,
            # USER ID 键（登录账号字符串，与行程头 owner_account_id 同源）
            "owner_account_id": owner_account_id,
''')

# 2) list_groups: account param + union filter
sub('''    def list_groups(
        self,
        itinerary_id: str | None = None,
        owner_device_id: str | None = None,
        *,
        include_drafts: bool = True,
    ) -> dict:
''', '''    def list_groups(
        self,
        itinerary_id: str | None = None,
        owner_device_id: str | None = None,
        owner_account_id: str | None = None,
        *,
        include_drafts: bool = True,
    ) -> dict:
''')
sub('''        items = list(self._items.values())
        if not include_drafts:
            # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：草稿行
            # 只在规划引擎内部可见，看板/接口一律不返回
            items = [i for i in items if not i.get("draft_session_id")]
        if owner_device_id is not None:
            # 有归属的按设备隔离；无归属（历史行/脚本建行）仍可见——归属列
            # 是新事实，不能让老数据在升级瞬间集体消失。
            items = [
                i
                for i in items
                if i.get("owner_device_id") in (None, owner_device_id)
            ]
''', '''        items = list(self._items.values())
        if not include_drafts:
            # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：草稿行
            # 只在规划引擎内部可见，看板/接口一律不返回
            items = [i for i in items if not i.get("draft_session_id")]
        if owner_device_id is not None or owner_account_id is not None:
            # 2026-11-14（用户拍板「打开行程中心按 USER ID 出内容」）：本
            # 设备的行 + 本登录账号的行（换设备登录也看得到）都算「我的」；
            # 无归属（历史行/脚本建行）仍可见——归属列是新事实，不能让老
            # 数据在升级瞬间集体消失；别人的行（别的设备且别的账号）隐藏。
            def _mine(item: dict) -> bool:
                row_dev = item.get("owner_device_id")
                row_acct = item.get("owner_account_id")
                if row_dev is None and row_acct is None:
                    return True  # 历史无归属行：维持原可见口径
                if owner_device_id is not None and row_dev == owner_device_id:
                    return True
                if owner_account_id is not None and row_acct == owner_account_id:
                    return True
                return False

            items = [i for i in items if _mine(i)]
''')

# 3) commit_drafts: stamp account
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
sub('''            item["draft_session_id"] = None
            if not item.get("itinerary_id"):
                item["itinerary_id"] = itinerary_id
            item["updated_at"] = _iso_now(None)
''', '''            item["draft_session_id"] = None
            if not item.get("itinerary_id"):
                item["itinerary_id"] = itinerary_id
            # 转正即落 USER ID（登录账号）——看板按用户出内容
            if owner_account_id and not item.get("owner_account_id"):
                item["owner_account_id"] = owner_account_id
            item["updated_at"] = _iso_now(None)
''')

# 4) _find_duplicate: account-aware owner match
sub('''        active = self._items.values() if items is None else items
        if owner_device_id is not None:
            # 2026-11-13：别的设备的同名行不是同一条心愿——各设备各一行
            active = [
                i
                for i in active
                if not i.get("owner_device_id")
                or i.get("owner_device_id") == owner_device_id
            ]
''', '''        active = self._items.values() if items is None else items
        if owner_device_id is not None or owner_account_id is not None:
            # 2026-11-13：别的用户的同名行不是同一条心愿。2026-11-14（用户
            # 拍板「心愿单按 USER ID 走」）：同一登录账号换设备也认领同一行
            # ——设备或账号任一命中即本人；两者都空（历史行）仍参与查重。
            def _owner_matches(item: dict) -> bool:
                row_dev = item.get("owner_device_id")
                row_acct = item.get("owner_account_id")
                if row_dev is None and row_acct is None:
                    return True
                if owner_device_id is not None and row_dev == owner_device_id:
                    return True
                if owner_account_id is not None and row_acct == owner_account_id:
                    return True
                return False

            active = [i for i in active if _owner_matches(i)]
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("trip_items ok")
