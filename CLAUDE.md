# CLAUDE.md - project guide for Claude Code

## What this repository is

ChinaTrip is an AI travel-agent system. Application code lives in
`CHINATRIP CODES/`; system design in `DESIGN/travel_agent_system_design.md`
and `DESIGN/architecture_diagram.png`; operational notes in `DAILY OPERATION/`.

## Layout

- `CHINATRIP CODES/` - application code (create app/, tests/, etc. here)
- `DESIGN/` - architecture and system design documents
- `DAILY OPERATION/` - operational routines and notes
- `scripts/` - CI tooling (deepseek_pr_review.py is used by the AI PR review workflow)
- `.github/workflows/` - PR gate, CI, AI review, auto-fix, auto-approve

## Conventions

- Python: PEP 8, linted/formatted with ruff (CI runs `ruff check` and
  `ruff format --check` over app/ scripts/ services/ tests/ when they exist).
- Tests in `tests/`, run with pytest; keep coverage >= 75 percent.
- Keep secrets (.env, API keys, tokens) out of the repository - .gitignore covers them.
- Dates in ISO 8601 (2026-10-17); amounts in CNY where relevant.

## Working rule: never stop to ask mid-task

In case of errors or mid progress: no asking — keep working until the task
is complete. Decide and continue on your own judgment; report issues in the
final summary instead of pausing.

## Iron rule: full source priority list on every fill

Whenever any job, script or backfill fills a POI field from candidate
sources (intro, duration, hours, rating, ticket, name_en, coordinates,
category, ...), it must walk the FULL source priority list — never a single
source, never an ad-hoc subset, never a job-private ordering. Canonical
order (the `_SOURCE_PRIORITY` tuple, documented in
`DESIGN/POIS_DATASOURCE.md` 读侧接线):

    unesco > 5a > museum1 > museum2 > museum3 > artmuseum
        > street > histown > amap > chinatravel > osm

- A new source registered into the pool must be appended to this list in
  the same change that introduces it.
- A new filling job copies the full list as-is (import/share a single
  definition rather than re-typing a shortened one).
- Existing jobs found with a shortened list are a bug: fix them to the
  full list.

## Local dev server (Windows)

Do NOT run uvicorn with --reload on this machine: its Windows reloader
leaves zombie spawn workers that keep serving stale code (the reload
log says reloading while responses stay old). Use the managed watcher
instead - single uvicorn process plus forced tree-kill restarts:

    dev_server.cmd watch     # hot reload; Ctrl+C stops (repo root)
    dev_server.cmd stop | start | restart | status

Detached-mode logs land in devlogs/ (gitignored).

## Pull-request flow


Branch from main, open a PR. The automated gate blocks merge until CI passes;
an AI review comments on the diff; auto-fix applies lint fixes. See README.md.
