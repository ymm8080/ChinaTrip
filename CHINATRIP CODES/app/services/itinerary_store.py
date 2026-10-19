"""Itinerary working-copy store + snapshot versions (design v2.0 §5.4/§6.8).

Sync contract implemented here:
- ``working_sync_version`` +1 on every successful change (§5.4); a change
  with error-severity violations leaves both the version and the working
  copy untouched.
- Snapshots are server-side authoritative and immutable (§5.4, iron
  rule 16): once appended they are never modified — this module exposes
  no snapshot-mutation path, and ``restore`` only rewrites the working
  copy.
- The snapshot cap goes through ``EntitlementService.check_and_consume``
  (feature "snapshot", §6.8 ①) — no hardcoded limits.

No DB in this milestone: ``InMemoryItineraryStore`` is a plain dict. The
``ItineraryStore`` Protocol exists so a Postgres-backed implementation can
drop in later (swap the dependency factory in the API layer) without
touching ``ItineraryService`` or the endpoints.
"""

from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from app.services.entitlement import EntitlementService, TriggerEvent
from app.services.itinerary import (
    ChangeSummary,
    DayPlan,
    DiffOp,
    ItineraryPlan,
    PoiHours,
    ValidationReport,
)
from app.services.itinerary.pipeline import mutate as pipeline_mutate


class QuotaExceededError(Exception):
    """§6.8: quota exhausted — ``paywall_trigger`` is what the client feeds
    to its PaywallGate reporting loop (server 402 body mirrors it)."""

    def __init__(self, paywall_trigger: str, denied_reason: str | None = None) -> None:
        super().__init__(f"{denied_reason or 'quota_exhausted'}:{paywall_trigger}")
        self.paywall_trigger = paywall_trigger
        self.denied_reason = denied_reason


class Snapshot(BaseModel):
    """One immutable server-side version (§5.4, iron rule 16)."""

    snapshot_id: str
    name: str  # auto "v1", "v2", ... when the caller passes none
    note: str | None = None
    sync_version: int  # working_sync_version at freeze time
    plan: ItineraryPlan
    created_at: datetime


class ItineraryRecord(BaseModel):
    """A itinerary plus its version history. ``plan`` is the ONLY mutable
    copy — snapshots and their plans are frozen forever."""

    itinerary_id: str
    owner_device_id: str
    plan: ItineraryPlan  # working copy
    working_sync_version: int = 1
    snapshots: list[Snapshot] = Field(default_factory=list)
    active_snapshot_id: str | None = None
    # set when claimed by / created for a logged-in account
    owner_account_id: str | None = None


class ItineraryStore(Protocol):
    """Persistence for itinerary records.

    dict-backed in-process now; a later Postgres-backed store implements the
    same Protocol (plus id allocation) and replaces ``get_store`` in the API
    dependency factory — nothing else changes.
    """

    def new_itinerary_id(self) -> str: ...
    def new_snapshot_id(self) -> str: ...
    def get(self, itinerary_id: str) -> ItineraryRecord | None: ...

    def put(self, record: ItineraryRecord) -> None:
        """Upsert semantics: insert or replace by itinerary_id."""

    def delete(self, itinerary_id: str) -> bool: ...
    def list_by_owner(self, owner_device_id: str) -> list[ItineraryRecord]: ...
    def list_by_account(self, username: str) -> list[ItineraryRecord]: ...


class InMemoryItineraryStore:
    """dict-backed Protocol implementation + uuid4 id allocation.

    Concurrency: the API endpoints are ``async def`` on a single event loop
    and every service method below is synchronous (no awaits inside), so
    there is no interleaving point — no lock. A multi-process deployment
    must swap in a shared store via the Protocol anyway.
    """

    def __init__(self) -> None:
        self._records: dict[str, ItineraryRecord] = {}

    def new_itinerary_id(self) -> str:
        return f"it_{uuid4().hex}"

    def new_snapshot_id(self) -> str:
        return f"snap_{uuid4().hex}"

    def get(self, itinerary_id: str) -> ItineraryRecord | None:
        return self._records.get(itinerary_id)

    def put(self, record: ItineraryRecord) -> None:
        self._records[record.itinerary_id] = record

    def delete(self, itinerary_id: str) -> bool:
        return self._records.pop(itinerary_id, None) is not None

    def list_by_owner(self, owner_device_id: str) -> list[ItineraryRecord]:
        return [
            r for r in self._records.values() if r.owner_device_id == owner_device_id
        ]

    def list_by_account(self, username: str) -> list[ItineraryRecord]:
        return [r for r in self._records.values() if r.owner_account_id == username]


class ItineraryService:
    """Business rules over the store: version bumps (§5.4), snapshot quota
    (§6.8), restore semantics (iron rule 16). Stateless besides the store."""

    def __init__(self, store: ItineraryStore) -> None:
        self._store = store

    def create(
        self,
        owner_device_id: str,
        cities: list[str],
        days_count: int | None = None,
    ) -> ItineraryRecord:
        """New itinerary starting from an empty plan (days_count=None) or
        ``days_count`` empty day plans based in the first city."""
        days = (
            []
            if days_count is None
            else [DayPlan(day=i, base_city=cities[0]) for i in range(1, days_count + 1)]
        )
        itinerary_id = self._store.new_itinerary_id()
        record = ItineraryRecord(
            itinerary_id=itinerary_id,
            owner_device_id=owner_device_id,
            plan=ItineraryPlan(
                itinerary_id=itinerary_id, cities=list(cities), days=days
            ),
        )
        self._store.put(record)
        return record

    def mutate(
        self,
        record: ItineraryRecord,
        diffs: list[DiffOp],
        *,
        poi_hours: list[PoiHours] | None = None,
    ) -> tuple[ItineraryRecord, ValidationReport, ChangeSummary]:
        """Iron rule 0 one-shot mutation via the shared pipeline.

        Success (no error violations): working copy replaced and
        ``working_sync_version`` +1 (§5.4), record persisted. Error
        violations: record and version untouched — the caller maps the
        report to HTTP 422. Malformed diffs raise ``PipelineError``
        (caller maps to 400). ``old_plan`` is passed so iron rule 19
        (pinned items) is enforced on every change source.
        """
        new_plan, report, summary = pipeline_mutate(
            record.plan,
            diffs,
            poi_hours=poi_hours or [],
            old_plan=record.plan,
        )
        if report.ok:
            record.plan = new_plan
            record.working_sync_version += 1
            self._store.put(record)
        return record, report, summary

    def create_snapshot(
        self,
        record: ItineraryRecord,
        *,
        name: str | None = None,
        note: str | None = None,
        entitlement: EntitlementService,
        subject_id: str,
    ) -> Snapshot:
        """Freeze the current working copy as a new immutable snapshot.

        Quota first (§6.8 ①): ``check_and_consume("snapshot", ...)``;
        denial raises ``QuotaExceededError`` carrying the paywall trigger.
        The snapshot deep-copies the working plan at the current
        ``working_sync_version`` and is never modified afterwards — no
        update path exists anywhere in this module (iron rule 16).
        """
        decision = entitlement.check_and_consume("snapshot", subject_id)
        if not decision.allowed:
            raise QuotaExceededError(
                paywall_trigger=str(
                    decision.paywall_trigger or TriggerEvent.SNAPSHOT_LIMIT_HIT
                ),
                denied_reason=decision.denied_reason,
            )
        snapshot = Snapshot(
            snapshot_id=self._store.new_snapshot_id(),
            name=name or f"v{len(record.snapshots) + 1}",
            note=note,
            sync_version=record.working_sync_version,
            plan=record.plan.model_copy(deep=True),
            created_at=datetime.now(timezone.utc),
        )
        record.snapshots.append(snapshot)
        self._store.put(record)
        return snapshot

    def restore(self, record: ItineraryRecord, snapshot_id: str) -> ItineraryRecord:
        """Iron rule 16: the snapshot itself is never touched — the working
        copy becomes a deep copy of its plan, ``working_sync_version`` +1
        (§5.4), and ``active_snapshot_id`` points at the restored snapshot.

        Raises ``KeyError`` when the snapshot does not exist (API: 404).
        """
        snapshot = next(
            (s for s in record.snapshots if s.snapshot_id == snapshot_id), None
        )
        if snapshot is None:
            raise KeyError(snapshot_id)
        record.plan = snapshot.plan.model_copy(deep=True)
        record.working_sync_version += 1
        record.active_snapshot_id = snapshot.snapshot_id
        self._store.put(record)
        return record
