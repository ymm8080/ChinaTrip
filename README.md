# ChinaTrip

AI travel-agent system - code, design documents and daily-operation notes.

## Layout

```
CHINATRIP CODES/    Application code
DESIGN/             Architecture and system design (travel_agent_system_design.md)
DAILY OPERATION/    Operational notes and routines
scripts/            CI tooling (AI PR review script)
.github/workflows/  PR gate, CI, AI review, auto-fix, auto-approve
```

## Pull-request process (mirrors AMINQT)

1. **Branch and PR** - work on a feature branch, push it, open a PR into `main`
   (browser: Compare and pull request, or `gh pr create`).
2. **PR Review Gate** (pr-gate.yml) - automatically requests changes so the
   merge button is blocked while checks run.
3. **CI** (ci.yml) - ruff lint + format check, ADR validation, pytest with
   coverage (each stage skips gracefully if there is nothing to check yet).
4. **AI review** (deepseek-pr-review.yml) - DeepSeek V4.1 Flash (via OpenCode
   Go) reviews the diff and posts findings as a PR comment.
5. **Auto-fix** (auto-fix.yml) - applies ruff format/lint fixes and pushes
   them to the PR branch (needs the GH_PAT secret to re-trigger CI).
6. **Auto-approve** (auto-approve.yml) - when all CI checks pass, the gate
   review is dismissed and the PR is ready to merge.

## Required repository secrets

| Secret | Purpose | Required? |
|---|---|---|
| OPENCODE_API_KEY | AI PR review (DeepSeek V4.1 Flash via OpenCode Go) | yes for AI review |
| DEEPSEEK_API_KEY | fallback AI provider | optional |
| GH_PAT | classic PAT (repo + workflow scopes) so auto-fix pushes re-trigger CI | recommended |

Recommended branch protection for `main`: require a pull request before
merging (Settings - Branches - Add branch ruleset).
