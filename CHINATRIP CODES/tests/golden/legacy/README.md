# Legacy recordings (`tests/golden/legacy/`)

Recorded **actual outputs of the legacy cascade** for corpus scenarios,
consumed by the shadow harness (`app/services/trip_solver/shadow/`) as
the "old engine" side of the diff report (F-61, audit M6 offline-batch).

Naming: `<scenario-stem>_legacy.json` next to the scenario fixture
(`../g01.json` ↔ `g01_legacy.json`).

Schema (v1):

```json
{
  "schema_version": 1,
  "engine": "legacy",
  "kind": "recorded-actual-output",
  "provenance": { "source": "...", "recorded_at": "..." },
  "days": [{ "day": 1, "items": [{
      "name": "...", "start": "HH:MM" | null, "end": "HH:MM" | null,
      "kind": "visit|meal|hotel", "requested": true|false|null,
      "remote": bool, "anchor": "meal anchor name",
      "leg": {"board": "HH:MM", "arrive": "HH:MM"},
      "entry_cap": "HH:MM"          // only where the recording carries it
  }]}],
  "unplaced": [{ "rid": "...", "name": "..." }],
  "disclosures": ["...verbatim strings..."]
}
```

Rules:

- **Verbatim, not idealized.** Card times, sequence, unplaced and
  disclosures are recorded exactly as the legacy engine produced them —
  including the defects (B-01 untimed card, B-02/B-03a fillers, B-03c
  card≠leg). The harness must *detect* those on the legacy side; that is
  the instrument's ground truth.
- **Anonymized** (M3): no device/account/session ids or emails.
- A scenario without a recording simply has no legacy side in the report
  (`legacy: null`) — never fabricate one. P2-B regenerates recordings
  from fresh incident dumps when the corpus expands.
- `entry_cap` is recorded only where the legacy response exposed it; the
  `no_entry_cap_breach` assertion skips cards without it (no heuristics).

## In-process replay recordings (P2-B)

`python -m app.services.trip_solver.shadow --replay-legacy` regenerates a
missing recording by replaying the snapshot through the REAL legacy cascade
(`PlanningAgent._generate_v0`) with every I/O stubbed from the snapshot
itself: the POI store serves exactly the snapshot's candidates, weather
comes from the snapshot's weather rows, the LLM is a boom sentinel
(algorithm mode is the default path and must stay zero-LLM), trains/flights
are the deterministic mocks. Each replay runs twice; `provenance` carries
`kind: "in-process-replay"`, `runs: 2`, `determinism: bool` (the two-run
calibration the `deterministic` assertion consumes on the legacy side),
`auto_restaurants: false` (meal-card fidelity and access-leg capture are
the next P2-B iteration — meal assertions pend honestly) and
`llm: "boom-sentinel"`.

Rules:

- Hand recordings (`kind: "recorded-actual-output"`) are **never**
  overwritten, with or without `--replay-force`; they are ground truth
  from incident dumps. `--replay-force` only refreshes existing
  in-process-replay recordings.
- Replay recordings carry per-item `city` (C-07 checks) and `poi_id`.
- Verbatim rule unchanged: card times/unplaced/disclosures are recorded
  exactly as the cascade produced them, defects included.
