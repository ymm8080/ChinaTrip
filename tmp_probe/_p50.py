# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\backfill.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''    refund_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class AllianceFeedItem''', '''    refund_summary: str | None = None
    # 2026-11-14（用户拍板「预订埋点也要 USER ID 列」）：登录账号随行留档
    owner_account_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AllianceFeedItem''')

sub('''    def create(
        self,
        *,
        action_type: str,
        channel: str,
        url: str,
        refund_summary: str | None = None,
    ) -> HandoffRecord:
''', '''    def create(
        self,
        *,
        action_type: str,
        channel: str,
        url: str,
        refund_summary: str | None = None,
        owner_account_id: str | None = None,
    ) -> HandoffRecord:
''')
sub('''            status=STATUS_OPENED,
            refund_summary=refund_summary,
            created_at=now,
''', '''            status=STATUS_OPENED,
            refund_summary=refund_summary,
            # 2026-11-14（用户拍板「预订埋点按 USER ID 落库」）
            owner_account_id=owner_account_id,
            created_at=now,
''')

sub('''                ActionHandoff(
                    id=row_id,
                    action_type=record.action_type,
                    channel=record.channel,
                    deeplink=record.url,
                    status=record.status,
''', '''                ActionHandoff(
                    id=row_id,
                    action_type=record.action_type,
                    channel=record.channel,
                    deeplink=record.url,
                    status=record.status,
                    # 2026-11-14（用户拍板「预订埋点按 USER ID 落库」）
                    owner_account_id=getattr(record, "owner_account_id", None),
''')
sub('''            row.status = record.status
            row.order_ref = record.order_ref
            row.source_channel = record.source_channel
''', '''            row.status = record.status
            row.order_ref = record.order_ref
            row.source_channel = record.source_channel
            # 2026-11-14：状态推进不改归属；仅补空 USER ID
            if getattr(record, "owner_account_id", None) and not row.owner_account_id:
                row.owner_account_id = record.owner_account_id
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("backfill ok")
