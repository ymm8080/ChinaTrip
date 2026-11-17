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

# 2) /plan/{sid}/message: account dep + stamp
sub('''@router.post("/plan/{session_id}/message")
async def message_plan(
    session_id: str,
    request: PlanMessageRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    gate: RequestGate = Depends(get_request_gate),
    fast_lane: FastLane = Depends(get_fast_lane),
    tasks: TaskStore = Depends(get_task_store),
) -> dict:
''', '''@router.post("/plan/{session_id}/message")
async def message_plan(
    session_id: str,
    request: PlanMessageRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    gate: RequestGate = Depends(get_request_gate),
    fast_lane: FastLane = Depends(get_fast_lane),
    tasks: TaskStore = Depends(get_task_store),
    account: str | None = Depends(_account_from_auth),
) -> dict:
''')
sub('''    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    # 换局闸（2026-11-13「重新规划却回到上次行程」）：这句话本身是另一趟完整
''', '''    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    # 2026-11-14（用户拍板「心愿单按 USER ID 出内容」）：会话记住登录账号
    session.account_id = account or session.account_id
    # 换局闸（2026-11-13「重新规划却回到上次行程」）：这句话本身是另一趟完整
''')

# 3) from-itinerary: stamp
sub('''    record = _owned_record(itinerary_store, itinerary_id, x_device_id, account)
    plan = record.plan.model_copy(deep=True)
''', '''    record = _owned_record(itinerary_store, itinerary_id, x_device_id, account)
    plan = record.plan.model_copy(deep=True)
    # 2026-11-14：✏️ 修改已存行程的会话也记住 USER ID（心愿行即时落账号）
''')
# find the session creation in from-itinerary to stamp account — check what follows
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("message ok")
