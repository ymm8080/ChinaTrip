"""Plan-agent API (design v2.0 §6.1-§6.3): progressive multi-city planning.

POST /api/v1/plan/start          — <=2 clarifications or an immediate v0
POST /api/v1/plan/{id}/message   — conversational diff iterations

X-Device-ID is required on both routes. LLM failures on the conversational
path map to 502 (extract.py style); the v0 path degrades to a placeholder
plan instead of failing (§6.1 time-to-first-itinerary contract).
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.agent.plan import (
    PlanningAgent,
    PlanSessionStore,
    clarify_questions,
    current_violations,
    get_plan_session_store,
)
from app.services.amap_client import AmapClient
from app.services.llm import get_llm_adapter
from app.services.llm.zhipu import LLMError
from app.services.trains import MockTrainService

router = APIRouter(prefix="/api/v1", tags=["plan"])
logger = logging.getLogger(__name__)


class PlanStartRequest(BaseModel):
    cities: list[str] | None = None
    days: int | None = None
    preferences: str = ""


class PlanMessageRequest(BaseModel):
    text: str = Field(min_length=1)


_agent_singleton: PlanningAgent | None = None


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
            train_service=MockTrainService(),
            time_budget_seconds=settings.solver_time_budget_seconds,
        )
    return _agent_singleton


def get_plan_sessions() -> PlanSessionStore:
    return get_plan_session_store()


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
        )
    except LLMError as exc:
        # LLMError messages are sanitized (never contain the API key).
        logger.exception("plan/start llm_error: %s", exc)
        raise HTTPException(status_code=502, detail="llm_error") from exc
    store.save(session)
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
    body: dict = {"reply": reply, "state": session.state}
    if session.state == "clarify":
        body["clarify"] = clarify_questions(session)
    if session.plan is not None:
        body["plan"] = session.plan
        body["violations"] = current_violations(session)
    if change is not None:
        body["change"] = change
    return body
