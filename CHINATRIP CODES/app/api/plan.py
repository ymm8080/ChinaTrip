"""Plan-agent API (design v2.0 §6.1-§6.3): progressive multi-city planning.

POST /api/v1/plan/start          — <=2 clarifications or an immediate v0
POST /api/v1/plan/{id}/message   — conversational diff iterations
POST /api/v1/plan/{id}/sites/confirm — H5 点选必去确认直插心愿单
POST /api/v1/plan/{id}/save      — explicit save: upsert the working
                                   copy into the itinerary store and
                                   freeze a snapshot (2026-10-20:
                                   planning NEVER auto-persists)

X-Device-ID is required on all routes. Transient LLM failures degrade
in-conversation (one retry, then a friendly reply — the session and plan
survive); the v0 path degrades to a placeholder plan instead of failing
(§6.1 time-to-first-itinerary contract). 502 stays as the safety net for
anything the agent still raises.
"""

import logging
import uuid
from datetime import datetime, time, timezone
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.itineraries import (
    _account_from_auth,
    _owned_record,
    get_entitlement_service,
    get_itinerary_service,
    get_store,
)
from app.api.translate import get_translation_service
from app.api.trip_items import get_trip_item_service
from app.config import Settings, get_settings
from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    PlanSessionStore,
    PoiStoreUnavailableError,
    clarify_questions,
    current_violations,
)
from app.services.ctrip_hours import get_ctrip_hours
from app.services.entitlement import EntitlementService
from app.services.fast_lane import FastLane
from app.services.gate import Lane, RequestGate
from app.services.itinerary import DiffOp, VisitItem, mutate
from app.services.itinerary_store import (
    ItineraryRecord,
    ItineraryService,
    QuotaExceededError,
)
from app.services.lane_metrics import get_lane_metrics
from app.services.lang_ctx import L
from app.services.llm import get_flash_adapter, get_llm_adapter
from app.services.llm.base import ChatMessage
from app.services.llm.zhipu import LLMError
from app.services.map_provider import build_map_client, map_ready
from app.services.poi_details import get_poi_detail_store
from app.services.state_persist import (
    PersistentPlanSessionStore,
    db_path_from_url,
    get_state_backend,
)
from app.services.task_queue import TaskStore, get_task_store
from app.services.trains import get_train_service
from app.services.translate import TranslationService

router = APIRouter(prefix="/api/v1", tags=["plan"])
logger = logging.getLogger(__name__)


class PlanStartRequest(BaseModel):
    cities: list[str] | None = None
    days: int | None = None
    preferences: str = ""
    city_days: dict[str, int] | None = None  # 目的地 → 停留天数（H5 每城天数）
    start_date: str | None = None  # 出发日期 ISO（可空）——随快照持久化
    lang: str | None = None  # 双语 P2：会话回复语言 "en"/"zh"（缺省 zh）


class PlanMessageRequest(BaseModel):
    text: str = Field(min_length=1)


class PlanSitesConfirmRequest(BaseModel):
    mandatory: list[str] = Field(default_factory=list)  # 点选的必去地点名


class PlanPinRequest(BaseModel):
    pinned: bool


_agent_singleton: PlanningAgent | None = None
_sessions_singleton: PersistentPlanSessionStore | None = None


def get_planning_agent(
    settings: Settings = Depends(get_settings),
) -> PlanningAgent:
    """Process-wide lazy singleton (translate.py pattern). No amap key
    means placeholder candidates, not a 503 — planning must still deliver."""
    global _agent_singleton
    if _agent_singleton is None:
        amap = build_map_client(settings) if map_ready(settings) else None
        _agent_singleton = PlanningAgent(
            get_llm_adapter(settings),
            amap_client=amap,
            train_service=get_train_service(settings),
            time_budget_seconds=settings.solver_time_budget_seconds,
            trip_items=get_trip_item_service(),
            poi_details=get_poi_detail_store(),
            ctrip_hours=get_ctrip_hours(),
        )
    return _agent_singleton


def get_plan_sessions() -> PlanSessionStore:
    """Process-wide persistent store: sessions survive uvicorn restarts."""
    global _sessions_singleton
    if _sessions_singleton is None:
        settings = get_settings()
        _sessions_singleton = PersistentPlanSessionStore(
            get_state_backend(db_path_from_url(settings.state_db_url))
        )
    return _sessions_singleton


_gate_singleton: RequestGate | None = None
_fast_lane_singleton: FastLane | None = None


def get_request_gate(settings: Settings = Depends(get_settings)) -> RequestGate:
    """§6.12 分类闸门进程级单例（translate.py 单例模式）。"""
    global _gate_singleton
    if _gate_singleton is None:
        _gate_singleton = RequestGate(
            get_flash_adapter(settings),
            intent_cache_ttl_seconds=settings.intent_cache_ttl_seconds,
            intent_cache_max_entries=settings.intent_cache_max_entries,
        )
    return _gate_singleton


def get_fast_lane(
    settings: Settings = Depends(get_settings),
    translate: TranslationService = Depends(get_translation_service),
) -> FastLane:
    """§6.12 快车道处理器单例（答案缓存 TTL/容量走 settings）。
    translate 必须走 Depends 注入——直接调 get_translation_service()
    会把裸 Depends 默认值当实参（2026-10-27 事故门禁）。"""
    global _fast_lane_singleton
    if _fast_lane_singleton is None:
        _fast_lane_singleton = FastLane(
            poi_details=get_poi_detail_store(),
            trip_items=get_trip_item_service(),
            translate=translate,
            answer_ttl_seconds=settings.fast_lane_answer_ttl_seconds,
            answer_max_entries=settings.fast_lane_answer_max_entries,
        )
    return _fast_lane_singleton


class PlanSaveRequest(BaseModel):
    name: str | None = None
    note: str | None = None
    # 2026-10-25 旧行程自愈：itinEdit 对没存过出发日期的行程缺省「今天」，
    # 随保存落库（None = 不改 plan 里已有的值）
    start_date: str | None = None


@router.post("/plan/{session_id}/save", status_code=201)
async def save_plan(
    session_id: str,
    request: PlanSaveRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: PlanSessionStore = Depends(get_plan_sessions),
    itinerary_store=Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    entitlement: EntitlementService = Depends(get_entitlement_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    """Explicit save (2026-10-20 product rule: 行程只在用户点「💾 保存行程」
    时写入行程库). Upserts the session's working plan into the itinerary
    store (owner = device; a Bearer account claims it) and freezes one
    immutable snapshot — quota denial answers 402 with the paywall
    trigger, while the working copy stays persisted."""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="nothing_to_save")
    plan = session.plan
    if request.start_date and request.start_date != plan.start_date:
        plan = plan.model_copy(update={"start_date": request.start_date})
        session.plan = plan
        store.save(session)
    record = itinerary_store.get(plan.itinerary_id)
    if record is None:
        record = ItineraryRecord(
            itinerary_id=plan.itinerary_id,
            owner_device_id=x_device_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            plan=plan,
        )
    else:
        record.plan = plan
        record.working_sync_version += 1
        record.updated_at = datetime.now(timezone.utc)
    if account is not None and not record.owner_account_id:
        record.owner_account_id = account
    itinerary_store.put(record)
    try:
        snapshot = service.create_snapshot(
            record,
            name=request.name,
            note=request.note,
            entitlement=entitlement,
            subject_id=x_device_id,
        )
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "denied_reason": exc.denied_reason or "quota_exhausted",
                "paywall_trigger": exc.paywall_trigger,
            },
        ) from exc
    return snapshot.model_dump(exclude={"plan"})


@router.post("/plan/from-itinerary/{itinerary_id}", status_code=201)
async def start_plan_from_itinerary(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: PlanSessionStore = Depends(get_plan_sessions),
    itinerary_store=Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    """继续修改已有行程（2026-10-20：「行程」页 ✏️ 修改）——deep-copy 该
    行程的工作副本开一个新规划会话（state=ready），对话改动照走铁律
    管线；「💾 保存行程」按原 itinerary_id 覆盖并冻结新快照。Unknown /
    foreign-owner ids answer 404（itineraries 同款防枚举）。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    record = _owned_record(itinerary_store, itinerary_id, x_device_id, account)
    plan = record.plan.model_copy(deep=True)
    session = PlanSession(
        session_id=uuid.uuid4().hex,
        device_id=x_device_id,
        cities=list(plan.cities),
        days=len(plan.days),
        state="ready",
        plan=plan,
        assumptions=list(plan.assumptions),
        history=[
            ChatMessage(
                role="assistant",
                content=(
                    L(
                        f"已载入行程 {itinerary_id}（{':'.join(plan.cities)}，"
                        f"{len(plan.days)} 天）。直接说要怎么改（例如：把第二天的"
                        "景点挪到第三天、加一天）；改完点「💾 保存行程」覆盖保存。",
                        f"Itinerary {itinerary_id} loaded ({':'.join(plan.cities)}, "
                        f"{len(plan.days)} days). Just say what to change (e.g. move "
                        "day-2 sights to day 3, or add a day); tap '💾 Save Itinerary' "
                        "to overwrite when done.",
                    )
                ),
            )
        ],
    )
    store.save(session)
    body: dict = {"session_id": session.session_id, "state": session.state}
    body["plan"] = session.plan
    body["assumptions"] = session.assumptions
    body["violations"] = current_violations(session)
    return body


@router.post("/plan/start")
async def start_plan(
    request: PlanStartRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    try:
        session = await agent.start(
            device_id=x_device_id,
            cities=request.cities or [],
            days=request.days or 0,
            preferences=request.preferences or "",
            city_days=request.city_days,
            start_date=request.start_date,
            lang=request.lang,
        )
    except PoiStoreUnavailableError:
        # 库降级（DB 锁存+空内存）不出占位假行程——干净 503 让前端
        # 提示稍后重试（2026-10-25 占位事故门禁）。
        logger.warning("plan/start poi_store_unavailable")
        raise HTTPException(status_code=503, detail="poi_store_unavailable")
    except LLMError as exc:
        # LLMError messages are sanitized (never contain the API key).
        logger.exception("plan/start llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
    body: dict = {"session_id": session.session_id, "state": session.state}
    if session.state == "clarify":
        body["clarify"] = clarify_questions(session)
        return body
    if session.state == "site_confirm":
        body["sites"] = session.pending_sites
        if session.history and session.history[-1].role == "assistant":
            body["reply"] = session.history[-1].content
        body["clarify"] = clarify_questions(session)
        return body
    if session.state == "resto_confirm":
        body["restos"] = [r.model_dump() for r in session.pending_restos]
        if session.history and session.history[-1].role == "assistant":
            body["reply"] = session.history[-1].content
    body["plan"] = session.plan
    body["assumptions"] = session.assumptions
    body["violations"] = current_violations(session)
    return body


@router.post("/plan/{session_id}/message")
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
    """§6.12 双车道分流的消息回合：闸门分类 → 快车道直答 / 慢车道入队
    「已受理」/ 主车道走完整 agent 管线。每回合记 lane + 耗时指标。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    metrics = get_lane_metrics()
    started = monotonic()

    decision = await gate.classify(request.text)

    if decision.lane is Lane.fast:
        answer = await fast_lane.answer(session, request.text, decision.intent)
        if answer is not None:
            session.history.append(ChatMessage(role="user", content=request.text))
            session.history.append(ChatMessage(role="assistant", content=answer.text))
            store.save(session)
            metrics.record(
                "fast",
                ttft_ms=(monotonic() - started) * 1000.0,
                intent=decision.intent,
                source=decision.source,
            )
            body = _plan_turn_body(session, answer.text, None)
            body["lane"] = {"lane": "fast", "intent": decision.intent}
            return body
        # 快车道答不出（宁缺毋错）：落主车道继续，不虚构。
    elif decision.lane is Lane.slow:
        task = tasks.enqueue(
            "replan",
            {
                "session_id": session.session_id,
                "device_id": x_device_id,
                "text": request.text,
            },
            device_id=x_device_id,
        )
        metrics.record(
            "slow",
            ttft_ms=(monotonic() - started) * 1000.0,
            intent=decision.intent,
            source=decision.source,
        )
        body = _plan_turn_body(
            session,
            L(
                "收到，重排已在后台进行，完成后会通知你（任务 "
                f"{task.task_id[:8]}…可稍后刷新查看）",
                "Got it — replanning in the background; you'll be notified"
                f" when done (task {task.task_id[:8]}…).",
            ),
            None,
        )
        body["lane"] = {
            "lane": "slow",
            "intent": decision.intent,
            "task_id": task.task_id,
        }
        return body

    try:
        session, reply, change = await agent.message(session, request.text)
    except PoiStoreUnavailableError:
        logger.warning("plan/message poi_store_unavailable")
        raise HTTPException(status_code=503, detail="poi_store_unavailable")
    except LLMError as exc:
        logger.exception("plan/message llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    metrics.record(
        "main",
        ttft_ms=(monotonic() - started) * 1000.0,
        intent=decision.intent,
        source=decision.source,
    )
    store.save(session)
    body = _plan_turn_body(session, reply, change)
    body["lane"] = {"lane": "main", "intent": decision.intent}
    return body


def _plan_turn_body(session, reply: str, change) -> dict:
    """Shared response envelope for message + sites/confirm turns."""
    body: dict = {"reply": reply, "state": session.state}
    if session.state == "site_confirm":
        body["sites"] = session.pending_sites
    if session.state == "resto_confirm":
        body["restos"] = [r.model_dump() for r in session.pending_restos]
    if session.state == "clarify":
        body["clarify"] = clarify_questions(session)
    if session.plan is not None:
        body["plan"] = session.plan
        body["violations"] = current_violations(session)
    if change is not None:
        body["change"] = change
    return body


@router.post("/plan/{session_id}/sites/confirm")
async def confirm_plan_sites(
    session_id: str,
    request: PlanSitesConfirmRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """H5 点选「必去」确认（product rule 2026-10-20）：the picked names
    ride straight to the wishlist write + pipeline — no composed text
    to re-parse; unpicked candidates are never recorded."""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.state != "site_confirm" or not session.pending_sites:
        raise HTTPException(status_code=409, detail="not_awaiting_sites")
    try:
        session, reply, change = await agent.confirm_sites(session, request.mandatory)
    except PoiStoreUnavailableError:
        logger.warning("plan/sites_confirm poi_store_unavailable")
        raise HTTPException(status_code=503, detail="poi_store_unavailable")
    except LLMError as exc:
        logger.exception("plan/sites_confirm llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
    return _plan_turn_body(session, reply, change)


def _find_visit_item(plan, item_id: str) -> VisitItem | None:
    for day in plan.days:
        for item in day.items:
            if isinstance(item, VisitItem) and item.item_id == item_id:
                return item
    return None


@router.post("/plan/{session_id}/items/{item_id}/pin")
async def pin_plan_item(
    session_id: str,
    item_id: str,
    request: PlanPinRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """钉住/取消钉住（iron rule 19）：pinned 的项目引擎不重排时间。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    item = _find_visit_item(session.plan, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    if request.pinned and item.start_time is None:
        raise HTTPException(status_code=422, detail="pinned_requires_time")
    item.pinned = request.pinned
    store.save(session)
    reply = (
        L(f"已钉住 {item.name}", f"Pinned {item.name}")
        if request.pinned
        else L(f"已取消钉住 {item.name}", f"Unpinned {item.name}")
    )
    return _plan_turn_body(session, reply, None)


@router.post("/plan/{session_id}/items/{item_id}/delete")
async def delete_plan_item(
    session_id: str,
    item_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """删除按钮 = 用户对这一项的明确同意：mutate 不带 old_plan，rule 19
    不拦按钮删除；删除结果回写行程中心（记入「不想去」）。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    item = _find_visit_item(session.plan, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    plan_before = session.plan
    diff = DiffOp(op="remove", item_id=item_id)
    new_plan, _, _ = mutate(plan_before, [diff], poi_hours=[])
    session.plan = new_plan
    agent.sync_removals_to_trip_items(plan_before, [diff])
    store.save(session)
    reply = L(
        f"已删除 {item.name}，已记入不想去",
        f"Deleted {item.name} — recorded under 'not interested'",
    )
    return _plan_turn_body(session, reply, None)


class PlanMoveRequest(BaseModel):
    day: int = Field(ge=1)
    after_item_id: str | None = Field(default=None, max_length=32)


@router.post("/plan/{session_id}/items/{item_id}/move")
async def move_plan_item(
    session_id: str,
    item_id: str,
    request: PlanMoveRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """规划页拖拽（2026-10-24）：同天重排 / 跨天移动。用户顺序权威——
    引擎不跑 solver 重优化，清空受影响天非 pinned 景点时间后按新顺序
    重排时链（纯计算）；pinned 项 422 拒绝（前端无把手）。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, _, notes = agent.move_item(
            session, item_id, new_day=request.day, after_item_id=request.after_item_id
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    store.save(session)
    reply = L("已按你的顺序调整", "Reordered to your sequence") + (
        f"（{'；'.join(notes)}）" if notes else ""
    )
    return _plan_turn_body(session, reply, None)


class PlanRetimeRequest(BaseModel):
    start_time: time  # "HH:MM"


@router.post("/plan/{session_id}/items/{item_id}/retime")
async def retime_plan_item(
    session_id: str,
    item_id: str,
    request: PlanRetimeRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
) -> dict:
    """规划页点时间戳改时间（2026-10-24）：用户显式设时最高优先（pinned
    也允许改）；改后该景点成固定锚点，当天其余非 pinned 景点围绕它按
    顺序游标重排并按时间排序。"""
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.plan is None:
        raise HTTPException(status_code=400, detail="no_plan")
    try:
        _, summary, notes = agent.retime_item(
            session, item_id, start=request.start_time
        )
    except ValueError as exc:
        code = str(exc)
        if code == "item_not_found":
            raise HTTPException(status_code=404, detail="item_not_found") from None
        raise HTTPException(status_code=422, detail=code) from None
    store.save(session)
    base = (
        summary.change_summary[0]
        if summary.change_summary
        else L("已调整时间", "Time updated")
    )
    reply = base + (f"（{'；'.join(notes)}）" if notes else "")
    return _plan_turn_body(session, reply, None)
