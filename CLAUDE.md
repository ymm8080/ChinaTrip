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

## Pull-request flow

Branch from main, open a PR. The automated gate blocks merge until CI passes;
an AI review comments on the diff; auto-fix applies lint fixes. See README.md.
