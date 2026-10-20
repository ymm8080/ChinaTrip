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
