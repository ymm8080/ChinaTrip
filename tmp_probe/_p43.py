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

# 1) /plan/start: account dep + stamp session
sub('''@router.post("/plan/start")
async def start_plan(
    request: PlanStartRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
''', '''@router.post("/plan/start")
async def start_plan(
    request: PlanStartRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    account: str | None = Depends(_account_from_auth),
) -> dict:
''')
sub('''    except LLMError as exc:
        # LLMError messages are sanitized (never contain the API key).
        logger.exception("plan/start llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
''', '''    except LLMError as exc:
        # LLMError messages are sanitized (never contain the API key).
        logger.exception("plan/start llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    # 2026-11-14（用户拍板「心愿单/已排期按 USER ID 出内容」）：会话记住
    # 登录账号——会话里建的心愿行落 owner_account_id
    session.account_id = account or session.account_id
    store.save(session)
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("start ok")
