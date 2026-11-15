# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''    session = PlanSession(
        session_id=uuid.uuid4().hex,
        device_id=x_device_id,
''', '''    session = PlanSession(
        session_id=uuid.uuid4().hex,
        device_id=x_device_id,
        # 2026-11-14（用户拍板「心愿单按 USER ID 出内容」）：编辑会话带账号
        account_id=account,
''')

# save endpoint: pass account into commit
sub('''    agent.commit_wish_drafts(session)
    store.save(session)
''', '''    agent.commit_wish_drafts(session, account)
    store.save(session)
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("api plan ok")

# plan.py (agent): PlanSession.account_id field + create calls pass owner_account_id + commit_wish_drafts(account)
p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t2 = io.open(p2, encoding="utf-8", newline=None).read()

def sub2(old, new, n=1):
    global t2
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t2.count(old)
    assert c == n, (c, old[:100])
    t2 = t2.replace(old, new)

sub2('''    # 自由输入原句（2026-11-14「引擎不读输入」）：起步页那句话存下来，
''', '''    # USER ID（2026-11-14 用户拍板「心愿单/已排期按 USER ID 出内容」）：
    # 会话记住登录账号（owner_account_id 同源），建心愿行时随行落库。
    account_id: str | None = None
    # 自由输入原句（2026-11-14「引擎不读输入」）：起步页那句话存下来，
''')

sub2('''                    # 2026-11-14：未保存行程的心愿行是草稿（看板不显示）
                    draft_session_id=self._wish_draft_session(session),
                )
''', '''                    # 2026-11-14：未保存行程的心愿行是草稿（看板不显示）
                    draft_session_id=self._wish_draft_session(session),
                    # USER ID 键（登录账号，换设备登录也能看到）
                    owner_account_id=getattr(session, "account_id", None),
                )
''')

sub2('''                        # 2026-11-14：未保存行程的心愿行是草稿（看板不显示）
                        draft_session_id=self._wish_draft_session(session),
''', '''                        # 2026-11-14：未保存行程的心愿行是草稿（看板不显示）
                        draft_session_id=self._wish_draft_session(session),
                        # USER ID 键（登录账号，换设备登录也能看到）
                        owner_account_id=getattr(session, "account_id", None),
''')

sub2('''                    draft_session_id=(
                        self._wish_draft_session(session)
                        if session is not None
                        else None
                    ),
''', '''                    draft_session_id=(
                        self._wish_draft_session(session)
                        if session is not None
                        else None
                    ),
                    owner_account_id=(
                        getattr(session, "account_id", None)
                        if session is not None
                        else None
                    ),
''')

sub2('''    def commit_wish_drafts(self, session: PlanSession) -> int:
''', '''    def commit_wish_drafts(
        self, session: PlanSession, account: str | None = None
    ) -> int:
''')
sub2('''        hook = getattr(self._trip_items, "commit_drafts", None)
        committed = hook(itinerary_id, session.session_id) if callable(hook) else 0
''', '''        hook = getattr(self._trip_items, "commit_drafts", None)
        committed = (
            hook(
                itinerary_id,
                session.session_id,
                owner_account_id=(account or getattr(session, "account_id", None)),
            )
            if callable(hook)
            else 0
        )
''')

io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("agent ok")
