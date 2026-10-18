"""Tests for the entitlement service + paywall rule engine (§6.8 v1.5.1/2)."""

from datetime import datetime, timedelta

import pytest

from app.services.entitlement import (
    DEFAULT_QUOTAS,
    Decision,
    EntitlementService,
    InMemoryQuotaStore,
    OfferMatch,
    PaywallRuleConfig,
    TriggerEvent,
)

T0 = datetime(2026, 10, 18, 12, 0, 0)
CTX = {"device_id": "dev1", "trip_id": "trip1", "region": "OVERSEAS"}


def make_rule(**over):
    kw = dict(
        name="r1",
        enabled=True,
        priority=100,
        trigger_event=TriggerEvent.EMERGENCY_RESOLVED,
        conditions={},
        offer={"product_id": "exec_pass", "copy_key": "paywall.panic_resolved"},
        caps={},
    )
    kw.update(over)
    return PaywallRuleConfig(**kw)


def make_service(rules=None, **kw):
    return EntitlementService(InMemoryQuotaStore(), rules or [], **kw)


# -- default: everything free (§6.8 ⑥) --------------------------------------


def test_default_quotas_values():
    assert DEFAULT_QUOTAS["replan_per_trip"] == 1
    assert DEFAULT_QUOTAS["snapshot_limit"] == 3
    assert DEFAULT_QUOTAS["narration_tier"] == "free"


def test_no_rules_check_all_allowed_and_offer_none():
    svc = make_service()
    for feature in ("replan", "snapshot", "narration", "offline_pack"):
        d = svc.check_and_consume(feature, "trip1")
        assert isinstance(d, Decision)
        assert d.allowed
        assert d.denied_reason is None
    assert svc.match_offer("snapshot_limit_hit", CTX, now=T0) is None


def test_snapshot_free_limit_three_then_denied():
    svc = make_service()
    assert svc.check_and_consume("snapshot", "trip1").remaining == 2
    assert svc.check_and_consume("snapshot", "trip1").remaining == 1
    d = svc.check_and_consume("snapshot", "trip1")
    assert d.allowed and d.remaining == 0
    d4 = svc.check_and_consume("snapshot", "trip1")
    assert not d4.allowed
    assert d4.paywall_trigger == "snapshot_limit_hit"


def test_unknown_feature_and_narration_unlimited_by_default():
    svc = make_service()
    for _ in range(5):
        d = svc.check_and_consume("narration", "trip1")
        assert d.allowed and d.remaining == -1
        assert svc.check_and_consume("multi_city", "trip1").allowed


def test_quota_override_relaxes_limit():
    svc = make_service(quotas={"snapshot_limit": 10})
    for i in range(10):
        assert svc.check_and_consume("snapshot", "trip1").allowed
    assert not svc.check_and_consume("snapshot", "trip1").allowed


# -- quota exhaustion -> denied with correct paywall_trigger ----------------


def test_replan_quota_exhausted_denied_with_trigger():
    svc = make_service()
    assert svc.check_and_consume("replan", "trip1").allowed
    d = svc.check_and_consume("replan", "trip1")
    assert not d.allowed
    assert d.remaining == 0
    assert d.denied_reason == "quota_exhausted"
    assert d.paywall_trigger == "replan_quota_exhausted"


def test_quota_is_per_subject():
    svc = make_service()
    svc.check_and_consume("snapshot", "tripA")
    svc.check_and_consume("snapshot", "tripA")
    svc.check_and_consume("snapshot", "tripA")
    assert not svc.check_and_consume("snapshot", "tripA").allowed
    assert svc.check_and_consume("snapshot", "tripB").allowed


def test_denial_does_not_consume():
    svc = make_service()
    for _ in range(3):
        svc.check_and_consume("snapshot", "trip1")
    for _ in range(4):  # repeated denials must not grow the counter
        d = svc.check_and_consume("snapshot", "trip1")
        assert not d.allowed


# -- rule matching: trigger / enabled / kill_switch --------------------------


def test_trigger_event_mismatch_returns_none():
    svc = make_service([make_rule(trigger_event=TriggerEvent.SHARE_ITINERARY)])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is None


def test_disabled_rule_skipped():
    svc = make_service([make_rule(enabled=False)])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is None


def test_kill_switch_overrides_everything():
    svc = make_service([make_rule()])
    svc.kill_switch = True
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is None


def test_matching_rule_returns_offer_match():
    rule = make_rule()
    svc = make_service([rule])
    m = svc.match_offer("emergency_resolved", CTX, now=T0)
    assert isinstance(m, OfferMatch)
    assert m.rule_name == "r1"
    assert m.trigger_event == "emergency_resolved"
    assert m.offer == {"product_id": "exec_pass", "copy_key": "paywall.panic_resolved"}


# -- conditions: one by one ---------------------------------------------------


def test_condition_delay_minutes():
    svc = make_service([make_rule(conditions={"delay_minutes": 30})])
    svc.record_event("dev1", "emergency_resolved", T0)
    assert (
        svc.match_offer("emergency_resolved", CTX, now=T0 + timedelta(minutes=29))
        is None
    )
    m = svc.match_offer("emergency_resolved", CTX, now=T0 + timedelta(minutes=30))
    assert m is not None and m.rule_name == "r1"


def test_condition_delay_requires_recorded_event_for_that_device():
    svc = make_service([make_rule(conditions={"delay_minutes": 0})])
    svc.record_event("dev1", "emergency_resolved", T0)
    other = {**CTX, "device_id": "dev2"}
    assert svc.match_offer("emergency_resolved", other, now=T0) is None
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is not None


def test_condition_region():
    svc = make_service([make_rule(conditions={"region": "OVERSEAS"})])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is not None
    assert (
        svc.match_offer("emergency_resolved", {**CTX, "region": "DOMESTIC"}, now=T0)
        is None
    )


def test_condition_replan_quota_used_ge():
    svc = make_service([make_rule(conditions={"replan_quota_used": ">=1"})])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is None
    svc.check_and_consume("replan", "trip1")  # quota trail drives the condition
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is not None


def test_condition_replan_quota_used_other_operators():
    svc = make_service([make_rule(conditions={"replan_quota_used": "==0"})])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is not None
    svc.check_and_consume("replan", "trip1")
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is None


def test_condition_rollout_pct_zero_never_matches():
    svc = make_service([make_rule(conditions={"rollout_pct": 0})])
    for i in range(20):
        ctx = {**CTX, "subject_id": f"user-{i}"}
        assert svc.match_offer("emergency_resolved", ctx, now=T0) is None


def test_condition_rollout_pct_hundred_always_matches():
    svc = make_service([make_rule(conditions={"rollout_pct": 100})])
    for i in range(20):
        ctx = {**CTX, "subject_id": f"user-{i}"}
        assert svc.match_offer("emergency_resolved", ctx, now=T0) is not None


def test_condition_rollout_stable_for_same_subject():
    svc = make_service([make_rule(conditions={"rollout_pct": 50})])
    hits = 0
    for i in range(40):
        ctx = {**CTX, "subject_id": f"user-{i}"}
        first = svc.match_offer("emergency_resolved", ctx, now=T0 + timedelta(days=7))
        second = svc.match_offer("emergency_resolved", ctx, now=T0 + timedelta(days=8))
        assert (first is not None) == (second is not None)  # same id, same verdict
        hits += first is not None
    assert 0 < hits < 40  # pct=50 actually splits the population


def test_condition_rollout_falls_back_to_device_id():
    svc = make_service([make_rule(conditions={"rollout_pct": 100})])
    ctx = {"device_id": "dev9", "trip_id": "trip1"}  # no subject_id key
    assert svc.match_offer("emergency_resolved", ctx, now=T0) is not None


def test_unknown_condition_fails_closed():
    svc = make_service([make_rule(conditions={"totally_new_cond": 1})])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is None


# -- priority ordering --------------------------------------------------------


def test_priority_ascending_first_match_wins():
    lo = make_rule(name="lo", priority=10, offer={"product_id": "lo"})
    hi = make_rule(name="hi", priority=20, offer={"product_id": "hi"})
    svc = make_service([hi, lo])  # insertion order must not matter
    m = svc.match_offer("emergency_resolved", CTX, now=T0)
    assert m.rule_name == "lo" and m.offer["product_id"] == "lo"


def test_priority_tie_keeps_insertion_order():
    a = make_rule(name="a", priority=5)
    b = make_rule(name="b", priority=5)
    svc = make_service([a, b])
    assert svc.match_offer("emergency_resolved", CTX, now=T0).rule_name == "a"


# -- caps: per_trip_max / cooldown_hours --------------------------------------


def test_cap_per_trip_max_stops_after_limit():
    svc = make_service([make_rule(caps={"per_trip_max": 1})])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is not None
    assert (
        svc.match_offer("emergency_resolved", CTX, now=T0 + timedelta(minutes=1))
        is None
    )
    # cap is per trip: another trip still gets the offer
    assert (
        svc.match_offer("emergency_resolved", {**CTX, "trip_id": "trip2"}, now=T0)
        is not None
    )


def test_cap_cooldown_hours_blocks_then_expires():
    svc = make_service([make_rule(caps={"cooldown_hours": 24})])
    assert svc.match_offer("emergency_resolved", CTX, now=T0) is not None
    assert (
        svc.match_offer(
            "emergency_resolved", CTX, now=T0 + timedelta(hours=23, minutes=59)
        )
        is None
    )
    assert (
        svc.match_offer("emergency_resolved", CTX, now=T0 + timedelta(hours=24))
        is not None
    )


def test_caps_counted_per_rule_name_in_store():
    store = InMemoryQuotaStore()
    svc = EntitlementService(store, [make_rule(name="ruleA", caps={"per_trip_max": 2})])
    svc.match_offer("emergency_resolved", CTX, now=T0)
    svc.match_offer("emergency_resolved", CTX, now=T0 + timedelta(hours=48))
    assert store.get_used("shown:ruleA:trip1") == 2


# -- record_event trail --------------------------------------------------------


def test_record_event_rejects_unknown_event():
    svc = make_service()
    with pytest.raises(ValueError, match="unknown trigger_event"):
        svc.record_event("dev1", "made_up_event", T0)


def test_record_event_keeps_counter_trail():
    store = InMemoryQuotaStore()
    svc = EntitlementService(store, [])
    svc.record_event("dev1", "emergency_resolved", T0)
    svc.record_event("dev1", "emergency_resolved", T0 + timedelta(minutes=1))
    assert store.get_used("event:dev1:emergency_resolved") == 2


def test_trigger_event_enum_matches_design_catalog():
    expected = {
        "snapshot_limit_hit",
        "narration_preview_end",
        "multi_city_unlock",
        "offline_pack_download",
        "trip_day1_morning",
        "replan_quota_exhausted",
        "emergency_resolved",
        "narration_locked",
        "footprint_review",
        "share_itinerary",
    }
    assert {e.value for e in TriggerEvent} == expected
