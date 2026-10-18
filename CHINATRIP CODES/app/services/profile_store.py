"""Agent memory profile + link-history stores (design v2.4 §6.14 / §5 p.8).

The profile is viewable AND correctable: every field the user edits via PUT
is recorded in a per-device ``manually_set`` set so the post-session
distill (MVP: deterministic pure function, zero LLM — the async workflow
lands later) can never overwrite a human decision. Distilled writes carry
an undo ledger entry, so each applied fact is reversible; undo never marks
the field manual, leaving it distillable again.

Link history keeps both origins (user paste / agent recommend) with a
re-parse hook. The to-wishlist promotion glue is mainline's job — this
module only exposes the public store functions.
"""

import logging
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)

BUDGET_LEVELS = frozenset({"economy", "comfort", "luxury"})
COMPANIONS = frozenset({"solo", "couple", "family", "group"})
STAMINA_LEVELS = frozenset({"low", "medium", "high"})
SCALAR_FIELDS = frozenset({"budget_level", "companions", "stamina"})
LIST_FIELDS = frozenset({"travel_style", "dietary_restrictions"})
PROFILE_FIELDS = SCALAR_FIELDS | LIST_FIELDS | frozenset({"notes"})
_ENUMS = {
    "budget_level": BUDGET_LEVELS,
    "companions": COMPANIONS,
    "stamina": STAMINA_LEVELS,
}

# §6.5 confidence gate: below this a fact is only a suggestion.
DISTILL_APPLY_THRESHOLD = 0.8
MAX_LIST_ITEMS = 20
MAX_ITEM_CHARS = 64
MAX_NOTE_CHARS = 500
MAX_PROVENANCE_CHARS = 64

LINK_SOURCES = frozenset({"user_paste", "agent_recommend"})
LINK_ORIGINS = frozenset({"chat", "wishlist_boost", "booking_cards"})
LINK_STATUSES = frozenset({"pending", "parsed", "failed"})


class ProfileValidationError(ValueError):
    """str(exc) is the API detail code (invalid_profile / invalid_fact)."""


class LinkValidationError(ValueError):
    """str(exc) is the API detail code (invalid_url / invalid_source / ...)."""


def default_profile() -> dict:
    return {
        "budget_level": None,
        "travel_style": [],
        "dietary_restrictions": [],
        "companions": None,
        "stamina": None,
        "notes": [],
    }


@dataclass
class ProfileState:
    """Per-device mutable state; only ever handed out as deep copies."""

    profile: dict
    manually_set: set[str]
    item_provenance: dict[str, dict[str, str]]
    applied: dict[str, dict]
    updated_at: datetime


def new_profile_state(now: datetime) -> ProfileState:
    return ProfileState(
        profile=default_profile(),
        manually_set=set(),
        item_provenance={field: {} for field in LIST_FIELDS},
        applied={},
        updated_at=now,
    )


# --- validation helpers ------------------------------------------------------


def _clean_list_items(raw: list, *, code: str) -> list[str]:
    if not isinstance(raw, list) or len(raw) > MAX_LIST_ITEMS:
        raise ProfileValidationError(code)
    items: list[str] = []
    for element in raw:
        if not isinstance(element, str):
            raise ProfileValidationError(code)
        stripped = element.strip()
        if not stripped or len(stripped) > MAX_ITEM_CHARS:
            raise ProfileValidationError(code)
        if stripped not in items:
            items.append(stripped)
    return items


def _clean_note(raw: object, *, now: datetime) -> dict:
    if not isinstance(raw, dict):
        raise ProfileValidationError("invalid_profile")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_NOTE_CHARS:
        raise ProfileValidationError("invalid_profile")
    provenance = raw.get("provenance") or "user"
    if (
        not isinstance(provenance, str)
        or not provenance.strip()
        or len(provenance) > MAX_PROVENANCE_CHARS
    ):
        raise ProfileValidationError("invalid_profile")
    added_at = raw.get("added_at") or now.isoformat()
    return {
        "text": text.strip(),
        "provenance": provenance.strip(),
        "added_at": added_at,
    }


def _validated_patch(patch: dict, *, now: datetime) -> dict:
    clean: dict = {}
    for key, value in patch.items():
        if key not in PROFILE_FIELDS:
            raise ProfileValidationError("invalid_profile")
        if key in SCALAR_FIELDS:
            if value is None:
                clean[key] = None
            elif isinstance(value, str) and value.strip() in _ENUMS[key]:
                clean[key] = value.strip()
            else:
                raise ProfileValidationError("invalid_profile")
        elif key in LIST_FIELDS:
            clean[key] = _clean_list_items(value, code="invalid_profile")
        else:  # notes
            if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
                raise ProfileValidationError("invalid_profile")
            clean[key] = [_clean_note(note, now=now) for note in value]
    return clean


def _validated_fact(raw: dict) -> dict:
    key = raw.get("key")
    if key not in PROFILE_FIELDS:
        raise ProfileValidationError("invalid_fact")
    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ProfileValidationError("invalid_fact")
    if not 0.0 <= float(confidence) <= 1.0:
        raise ProfileValidationError("invalid_fact")
    provenance = raw.get("provenance")
    if (
        not isinstance(provenance, str)
        or not provenance.strip()
        or len(provenance) > MAX_PROVENANCE_CHARS
    ):
        raise ProfileValidationError("invalid_fact")
    value = raw.get("value")
    if key in SCALAR_FIELDS:
        if not isinstance(value, str) or value.strip() not in _ENUMS[key]:
            raise ProfileValidationError("invalid_fact")
        value = value.strip()
    elif key in LIST_FIELDS:
        items = [value] if isinstance(value, str) else value
        value = _clean_list_items(items, code="invalid_fact")
    else:  # notes
        if not isinstance(value, str) or not value.strip():
            raise ProfileValidationError("invalid_fact")
        if len(value) > MAX_NOTE_CHARS:
            raise ProfileValidationError("invalid_fact")
        value = value.strip()
    return {
        "key": key,
        "value": value,
        "confidence": float(confidence),
        "provenance": provenance.strip(),
    }


# --- distill pure function (independently unit-testable) ---------------------


def distill_facts(
    state: ProfileState,
    facts: list[dict],
    *,
    now: datetime,
    id_factory: Callable[[], str],
) -> tuple[ProfileState, list[dict], list[dict]]:
    """Deterministic zero-LLM distill (§6.14 MVP of the async workflow).

    Applies facts with confidence >= 0.8 whose field is not in
    ``manually_set`` (user edits always win); everything else — low
    confidence OR manually-set field — is returned as a suggestion. Never
    mutates the caller's state; clock and id generation are injected so the
    function is pure and reproducible.
    """
    new_state = ProfileState(
        profile=deepcopy(state.profile),
        manually_set=set(state.manually_set),
        item_provenance=deepcopy(state.item_provenance),
        applied=dict(state.applied),
        updated_at=state.updated_at,
    )
    applied: list[dict] = []
    suggestions: list[dict] = []
    for fact in facts:
        key, value = fact["key"], fact["value"]
        confidence, provenance = fact["confidence"], fact["provenance"]
        if confidence < DISTILL_APPLY_THRESHOLD or key in new_state.manually_set:
            suggestions.append({"key": key, "value": value, "confidence": confidence})
            continue
        applied_id = id_factory()
        if key in SCALAR_FIELDS:
            ledger = {"key": key, "kind": "scalar", "previous": new_state.profile[key]}
            new_state.profile[key] = value
        elif key in LIST_FIELDS:
            items = [value] if isinstance(value, str) else list(value)
            merged = list(new_state.profile[key])
            added: list[str] = []
            for item in items:
                if item not in merged:
                    merged.append(item)
                    added.append(item)
                new_state.item_provenance[key][item] = provenance
            new_state.profile[key] = merged
            ledger = {"key": key, "kind": "list", "added": added}
        else:  # notes
            note = {
                "text": value,
                "provenance": provenance,
                "added_at": now.isoformat(),
            }
            new_state.profile["notes"] = [*new_state.profile["notes"], note]
            ledger = {"key": key, "kind": "note", "note": note}
        new_state.applied[applied_id] = ledger
        applied.append({"applied_id": applied_id, "key": key, "value": value})
    if applied:
        new_state.updated_at = now
    return new_state, applied, suggestions


# --- profile store ------------------------------------------------------------


class ProfileStore:
    """In-memory per-device profile state (translate.py singleton pattern)."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock or datetime.now
        self._id_factory = id_factory or (lambda: uuid4().hex[:12])
        self._devices: dict[str, ProfileState] = {}

    def _state(self, device_id: str) -> ProfileState:
        state = self._devices.get(device_id)
        if state is None:
            state = new_profile_state(self._clock())
            self._devices[device_id] = state
        return state

    def get_profile(self, device_id: str) -> tuple[dict, str]:
        state = self._state(device_id)
        return deepcopy(state.profile), state.updated_at.isoformat()

    def merge(self, device_id: str, patch: dict) -> tuple[dict, str]:
        """Field-level merge; every key present in the patch is user-touched
        and therefore recorded in ``manually_set`` (explicit null clears)."""
        state = self._state(device_id)
        now = self._clock()
        clean = _validated_patch(patch, now=now)
        for key, value in clean.items():
            state.profile[key] = deepcopy(value)
            state.manually_set.add(key)
        state.updated_at = now
        return deepcopy(state.profile), state.updated_at.isoformat()

    def distill(self, device_id: str, facts: list[dict]) -> dict:
        state = self._state(device_id)
        checked = [_validated_fact(fact) for fact in facts]
        new_state, applied, suggestions = distill_facts(
            state, checked, now=self._clock(), id_factory=self._id_factory
        )
        self._devices[device_id] = new_state
        logger.info(
            "profile_distilled applied=%d suggestions=%d",
            len(applied),
            len(suggestions),
        )
        return {"applied": applied, "suggestions": suggestions}

    def undo(self, device_id: str, applied_id: str) -> tuple[dict, str]:
        """Reverse one distilled write (scalar -> previous value, list ->
        remove the added items, notes -> drop the appended entry)."""
        state = self._state(device_id)
        entry = state.applied.get(applied_id)
        if entry is None:
            raise KeyError(applied_id)
        kind = entry["kind"]
        if kind == "scalar":
            state.profile[entry["key"]] = entry["previous"]
        elif kind == "list":
            key = entry["key"]
            for item in entry["added"]:
                if item in state.profile[key]:
                    state.profile[key].remove(item)
                state.item_provenance.get(key, {}).pop(item, None)
        else:  # note
            note = entry["note"]
            if note in state.profile["notes"]:
                state.profile["notes"].remove(note)
        # Undo reverts the value but never marks the field manual, so the
        # field stays distillable (§6.14 "撤销后可再次蒸馏").
        del state.applied[applied_id]
        state.updated_at = self._clock()
        return deepcopy(state.profile), state.updated_at.isoformat()


# --- link history store -------------------------------------------------------


def _is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class LinkStore:
    """In-memory per-device link history, newest first."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock or datetime.now
        self._id_factory = id_factory or (lambda: uuid4().hex[:12])
        # device -> [(seq, record)]; seq breaks created_at ties deterministically.
        self._by_device: dict[str, list[tuple[int, dict]]] = {}

    def add_link(
        self,
        device_id: str,
        url: str,
        source: str,
        *,
        origin: str | None = None,
        itinerary_id: str | None = None,
    ) -> dict:
        if not isinstance(url, str) or not _is_http_url(url.strip()):
            raise LinkValidationError("invalid_url")
        if source not in LINK_SOURCES:
            raise LinkValidationError("invalid_source")
        if origin is not None and origin not in LINK_ORIGINS:
            raise LinkValidationError("invalid_origin")
        entries = self._by_device.setdefault(device_id, [])
        record = {
            "id": self._id_factory(),
            "url": url.strip(),
            "source": source,
            "origin": origin,
            "itinerary_id": itinerary_id,
            "status": "pending",
            "created_at": self._clock().isoformat(),
        }
        entries.append((len(entries), record))
        return deepcopy(record)

    def list_links(self, device_id: str) -> list[dict]:
        entries = sorted(
            self._by_device.get(device_id, []),
            key=lambda pair: (pair[1]["created_at"], pair[0]),
            reverse=True,
        )
        return [deepcopy(record) for _, record in entries]

    def get_link(self, device_id: str, link_id: str) -> dict | None:
        record = self._find(device_id, link_id)
        return deepcopy(record) if record is not None else None

    def set_status(self, device_id: str, link_id: str, status: str) -> dict:
        if status not in LINK_STATUSES:
            raise LinkValidationError("invalid_status")
        record = self._find(device_id, link_id)
        if record is None:
            raise KeyError(link_id)
        record["status"] = status
        return deepcopy(record)

    def reparse(self, device_id: str, link_id: str) -> dict:
        """MVP: deterministic parse marker; the real extraction later reuses
        the /extract pipeline. Idempotent by construction."""
        return self.set_status(device_id, link_id, "parsed")

    def _find(self, device_id: str, link_id: str) -> dict | None:
        for _, record in self._by_device.get(device_id, []):
            if record["id"] == link_id:
                return record
        return None
