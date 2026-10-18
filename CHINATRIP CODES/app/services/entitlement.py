"""Entitlement service + paywall rule engine (design v2.0 §6.8, v1.5.1/v1.5.2).

Principles (§6.8):
- Every paid touchpoint goes through this service; no hardcoded free/paid.
- Paywalls are a *rule table*, not fixed switches: when/where/who/what-offer
  is configuration, not code.
- Default policy = everything free (all rules enabled=false, quotas relaxed).
- caps + cooldown are the safety valve; kill_switch turns all offers off.
"""

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class TriggerEvent(StrEnum):
    """Paywall scenario catalog (§6.8 ③). New scenario = add enum + rule."""

    # 规划期
    SNAPSHOT_LIMIT_HIT = "snapshot_limit_hit"
    NARRATION_PREVIEW_END = "narration_preview_end"
    MULTI_CITY_UNLOCK = "multi_city_unlock"
    # 执行前
    OFFLINE_PACK_DOWNLOAD = "offline_pack_download"
    TRIP_DAY1_MORNING = "trip_day1_morning"
    # 执行中
    REPLAN_QUOTA_EXHAUSTED = "replan_quota_exhausted"
    EMERGENCY_RESOLVED = "emergency_resolved"
    NARRATION_LOCKED = "narration_locked"
    # 执行后
    FOOTPRINT_REVIEW = "footprint_review"
    SHARE_ITINERARY = "share_itinerary"


# Default free quotas (§6.8 ⑥: 默认策略=全免费，额度放宽). The paid snapshot
# cap of 10 is an upgrade state governed by the rule engine, not by defaults.
DEFAULT_QUOTAS: dict[str, int | str] = {
    "replan_per_trip": 1,
    "snapshot_limit": 3,
    "narration_tier": "free",
}

# feature -> (quota key in DEFAULT_QUOTAS, paywall trigger when exhausted).
# Unknown features are unlimited: default-free principle (§6.8 ①/⑥).
_FEATURE_RULES: dict[str, tuple[str, TriggerEvent]] = {
    "replan": ("replan_per_trip", TriggerEvent.REPLAN_QUOTA_EXHAUSTED),
    "snapshot": ("snapshot_limit", TriggerEvent.SNAPSHOT_LIMIT_HIT),
}

_ROLLING_PCT_MOD = 100
_CMP_RE = re.compile(r"^(>=|<=|==|>|<)\s*(\d+)$")


class QuotaStore(Protocol):
    """Counter storage. In-process now; swap for a DB-backed store later."""

    def get_used(self, key: str) -> int: ...

    def increment(self, key: str) -> int: ...


class InMemoryQuotaStore:
    """Process-local counter store. Keys are opaque `prefix:subject` strings."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def get_used(self, key: str) -> int:
        return self._counts.get(key, 0)

    def increment(self, key: str) -> int:
        used = self._counts.get(key, 0) + 1
        self._counts[key] = used
        return used


class PaywallRuleConfig(BaseModel):
    """Pure-pydantic twin of the PaywallRule row (no SQLAlchemy here)."""

    name: str
    enabled: bool = False  # §6.8 ②: 默认全关 = 全免费
    priority: int = 100
    trigger_event: TriggerEvent
    conditions: dict = Field(default_factory=dict)
    offer: dict = Field(default_factory=dict)
    caps: dict = Field(default_factory=dict)


class Decision(BaseModel):
    """Result of check_and_consume. remaining=-1 means unlimited."""

    allowed: bool
    remaining: int
    denied_reason: str | None = None
    # Set when denied by quota: the trigger_event the client should feed to
    # match_offer() to decide whether to raise the PaywallGate component.
    paywall_trigger: TriggerEvent | None = None


class OfferMatch(BaseModel):
    """What the client should render when a rule matches (§6.8 ④)."""

    rule_name: str
    trigger_event: TriggerEvent
    offer: dict


def _quota_key(feature: str, subject_id: str) -> str:
    return f"quota:{feature}:{subject_id}"


def _event_key(device_id: str, trigger_event: str) -> str:
    return f"event:{device_id}:{trigger_event}"


def _shows_key(rule_name: str, trip_id: str) -> str:
    return f"shown:{rule_name}:{trip_id}"


def _rollout_percentile(subject_id: str) -> int:
    """Stable hash bucket 0..99 for gray release (§6.8 ② rollout_pct)."""
    digest = hashlib.md5(subject_id.encode("utf-8")).hexdigest()  # noqa: S324
    return int(digest, 16) % _ROLLING_PCT_MOD


def _cmp(actual: int, spec: str | int) -> bool:
    """Evaluate '>=N' / '>N' / '<=N' / '<N' / '==N' / bare-N (exact)."""
    if isinstance(spec, int):
        return actual == spec
    m = _CMP_RE.match(str(spec).strip())
    if not m:
        return False
    op, bound = m.group(1), int(m.group(2))
    return {
        ">=": actual >= bound,
        ">": actual > bound,
        "<=": actual <= bound,
        "<": actual < bound,
        "==": actual == bound,
    }[op]


class EntitlementService:
    """Sync, pure-logic entitlement gate + offer matcher.

    Timestamps (event times, last-shown times) live on the service instance;
    counters live in the QuotaStore. A DB-backed deployment persists both.
    """

    def __init__(
        self,
        store: QuotaStore,
        rules: list[PaywallRuleConfig],
        *,
        quotas: Mapping[str, int | str] | None = None,
        kill_switch: bool = False,
    ) -> None:
        self.store = store
        self.rules = list(rules)
        self.quotas: dict[str, int | str] = {**DEFAULT_QUOTAS, **(quotas or {})}
        self.kill_switch = kill_switch
        self._event_times: dict[tuple[str, str], datetime] = {}
        self._last_shown: dict[str, datetime] = {}

    # -- §6.8 ①: paid touchpoints check entitlement here -------------------

    def check_and_consume(self, feature: str, subject_id: str) -> Decision:
        cfg = _FEATURE_RULES.get(feature)
        if cfg is None:
            if feature == "narration":
                # Tier-gated, not count-gated: free tier = unlimited use;
                # only an explicitly locked tier denies (§6.8 ③ narration).
                if self.quotas["narration_tier"] == "locked":
                    return Decision(
                        allowed=False,
                        remaining=0,
                        denied_reason="narration_locked",
                        paywall_trigger=TriggerEvent.NARRATION_PREVIEW_END,
                    )
            # Unknown features are unlimited: default-free principle.
            return Decision(allowed=True, remaining=-1)

        quota_key, trigger = cfg
        limit = int(self.quotas[quota_key])
        used = self.store.get_used(_quota_key(feature, subject_id))
        if used >= limit:
            return Decision(
                allowed=False,
                remaining=0,
                denied_reason="quota_exhausted",
                paywall_trigger=trigger,
            )
        self.store.increment(_quota_key(feature, subject_id))
        return Decision(allowed=True, remaining=limit - used - 1)

    # -- §6.8 ②: rule engine ------------------------------------------------

    def match_offer(
        self, trigger_event: str, context: dict, *, now: datetime
    ) -> OfferMatch | None:
        """First enabled rule (priority ascending) whose trigger, conditions
        and caps all pass. Returning a match counts as one display for caps.

        Context keys used: device_id, trip_id (or itinerary_id), region,
        subject_id (rollout identity; falls back to device_id/trip_id).
        """
        if self.kill_switch:  # §6.8 ⑤: 一键全局关闭
            return None
        for rule in sorted(self.rules, key=lambda r: r.priority):
            if not rule.enabled:
                continue
            if rule.trigger_event != trigger_event:
                continue
            if not self._conditions_pass(rule, context, now):
                continue
            if not self._caps_pass(rule, context, now):
                continue
            self._record_show(rule, context, now)
            return OfferMatch(
                rule_name=rule.name,
                trigger_event=rule.trigger_event,
                offer=rule.offer,
            )
        return None

    def _conditions_pass(
        self, rule: PaywallRuleConfig, context: dict, now: datetime
    ) -> bool:
        for key, expected in rule.conditions.items():
            if key == "delay_minutes":
                device_id = context.get("device_id", "")
                event_time = self._event_times.get((device_id, str(rule.trigger_event)))
                if event_time is None:
                    return False
                elapsed = (now - event_time).total_seconds() / 60.0
                if elapsed < float(expected):
                    return False
            elif key == "region":
                if context.get("region") != expected:
                    return False
            elif key == "replan_quota_used":
                subject = self._trip_subject(context)
                used = self.store.get_used(_quota_key("replan", subject))
                if not _cmp(used, expected):
                    return False
            elif key == "rollout_pct":
                subject_id = (
                    context.get("subject_id")
                    or context.get("device_id")
                    or context.get("trip_id")
                    or ""
                )
                if _rollout_percentile(str(subject_id)) >= float(expected):
                    return False
            else:
                # Unknown condition: fail closed — never show an offer the
                # engine does not fully understand (§6.8 ⑤ safety valve).
                return False
        return True

    def _caps_pass(self, rule: PaywallRuleConfig, context: dict, now: datetime) -> bool:
        caps = rule.caps or {}
        per_trip_max = caps.get("per_trip_max")
        if per_trip_max is not None:
            shown = self.store.get_used(
                _shows_key(rule.name, self._trip_subject(context))
            )
            if shown >= int(per_trip_max):
                return False
        cooldown_hours = caps.get("cooldown_hours")
        if cooldown_hours is not None:
            last = self._last_shown.get(rule.name)
            if last is not None and (now - last) < timedelta(
                hours=float(cooldown_hours)
            ):
                return False
        return True

    def _record_show(
        self, rule: PaywallRuleConfig, context: dict, now: datetime
    ) -> None:
        self.store.increment(_shows_key(rule.name, self._trip_subject(context)))
        self._last_shown[rule.name] = now

    # -- §6.8 ⑦: event trail (delay/cooldown input) --------------------------

    def record_event(self, device_id: str, trigger_event: str, now: datetime) -> None:
        try:
            TriggerEvent(trigger_event)
        except ValueError as exc:
            raise ValueError(f"unknown trigger_event: {trigger_event!r}") from exc
        self.store.increment(_event_key(device_id, trigger_event))
        self._event_times[(device_id, trigger_event)] = now

    @staticmethod
    def _trip_subject(context: dict) -> str:
        return str(context.get("trip_id") or context.get("itinerary_id") or "_anon_")
