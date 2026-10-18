"""Plan-agent API (design v2.0 §6.1-§6.3): progressive multi-city planning.

POST /api/v1/plan/start          — <=2 clarifications or an immediate v0
POST /api/v1/plan/{id}/message   — conversational diff iterations

X-Device-ID is required on both routes. Transient LLM failures degrade
in-conversation (one retry, then a friendly reply — the session and plan
survive); the v0 path degrades to a placeholder plan instead of failing
(§6.1 time-to-first-itinerary contract). 502 stays as the safety net for
anything the agent still raises.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.itineraries import get_store
from app.config import Settings, get_settings
from app.services.agent.plan import (
    PlanningAgent,
    PlanSessionStore,
    clarify_questions,
    current_violations,
)
from app.services.amap_client import AmapClient
from app.services.itinerary_store import ItineraryRecord
from app.services.llm import get_llm_adapter
from app.services.llm.zhipu import LLMError
from app.services.state_persist import (
    PersistentPlanSessionStore,
    db_path_from_url,
    get_state_backend,
)
from app.services.trains import get_train_service

router = APIRouter(prefix="/api/v1", tags=["plan"])
logger = logging.getLogger(__name__)


class PlanStartRequest(BaseModel):
    cities: list[str] | None = None
    days: int | None = None
    preferences: str = ""


class PlanMessageRequest(BaseModel):
    text: str = Field(min_length=1)


_agent_singleton: PlanningAgent | None = None
_sessions_singleton: PersistentPlanSessionStore | None = None


def get_planning_agent(
    settings: Settings = Depends(get_settings),
) -> PlanningAgent:
    """Process-wide lazy singleton (translate.py pattern). No amap key
    means placeholder candidates, not a 503 — planning must still deliver."""
    global _agent_singleton
    if _agent_singleton is None:
        amap = (
            AmapClient(
                key=settings.amap_api_key,
                base_url=settings.amap_base_url,
                timeout_seconds=settings.amap_timeout_seconds,
            )
            if settings.amap_api_key
            else None
        )
        _agent_singleton = PlanningAgent(
            get_llm_adapter(settings),
            amap_client=amap,
            train_service=get_train_service(settings),
            time_budget_seconds=settings.solver_time_budget_seconds,
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


def _persist_plan(device_id: str, session, store) -> None:
    """Mirror the working plan into the itinerary store so /itineraries
    endpoints and the H5 行程 tab see agent-produced plans (§5.4 working
    copy; +1 sync version on every change)."""
    plan = session.plan
    if plan is None:
        return
    record = store.get(plan.itinerary_id)
    if record is None:
        store.put(
            ItineraryRecord(
                itinerary_id=plan.itinerary_id,
                owner_device_id=device_id,
                plan=plan,
            )
        )
    else:
        record.plan = plan
        record.working_sync_version += 1
        store.put(record)


@router.post("/plan/start")
async def start_plan(
    request: PlanStartRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    agent: PlanningAgent = Depends(get_planning_agent),
    store: PlanSessionStore = Depends(get_plan_sessions),
    itinerary_store=Depends(get_store),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    try:
        session = await agent.start(
            device_id=x_device_id,
            cities=request.cities or [],
            days=request.days or 0,
            preferences=request.preferences or "",
        )
    except LLMError as exc:
        # LLMError messages are sanitized (never contain the API key).
        logger.exception("plan/start llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
    _persist_plan(x_device_id, session, itinerary_store)
    body: dict = {"session_id": session.session_id, "state": session.state}
    if session.state == "clarify":
        body["clarify"] = clarify_questions(session)
        return body
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
    itinerary_store=Depends(get_store),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    session = store.get(session_id, device_id=x_device_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    try:
        session, reply, change = await agent.message(session, request.text)
    except LLMError as exc:
        logger.exception("plan/message llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
    _persist_plan(x_device_id, session, itinerary_store)
    body: dict = {"reply": reply, "state": session.state}
    if session.state == "clarify":
        body["clarify"] = clarify_questions(session)
    if session.plan is not None:
        body["plan"] = session.plan
        body["violations"] = current_violations(session)
    if change is not None:
        body["change"] = change
    return body
