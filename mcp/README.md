# chinatrip — Toolchain & MCP setup notes

Generated 2026-10-17. Everything installed **without admin rights**, all heavy toolchain on **D:\dev** per user choice.

## Installed inventory

| Component | Location | Version / notes |
|---|---|---|
| JDK (Temurin) | `D:\dev\jdk` | 17.0.20; `JAVA_HOME` (User env) set |
| Android SDK | `D:\dev\android-sdk` | cmdline-tools (latest), platform-tools 37.0.1, platforms;android-35, build-tools;35.0.0; licenses accepted |
| Flutter SDK | `D:\dev\flutter` | stable 3.47.7 (SHA-verified zip); `D:\dev\flutter\bin` + `D:\dev\android-sdk\platform-tools` appended to User PATH |
| Dart SDK | `D:\dev\flutter\bin\cache\dart-sdk` | 3.13.5, ships inside Flutter; Dart MCP = `dart.exe mcp-server` (verified starting as a stdio server) |
| Flutter/Pub CN mirrors | User env | `FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`, `PUB_HOSTED_URL=https://pub.flutter-io.cn` |
| LiteLLM (+proxy extras) | vendor Python 3.13 site-packages | `litellm` CLI on PATH; run gateway: `litellm --config litellm_config.yaml --port 4000` |
| sentry-cli | npm global (`D:\tools\npm-global`) | 3.8.0; login once with `sentry-cli login` |
| Amap MCP | workspace `mcp\node_modules\@amap\amap-maps-mcp-server` | 0.0.8, stdio, needs `AMAP_MAPS_API_KEY` |
| Sentry MCP | workspace `mcp\node_modules\@sentry\mcp-server` | 0.42.0, stdio, needs `SENTRY_ACCESS_TOKEN` |
| Postgres MCP (crystaldba) | `D:\dev\venvs\postgres-mcp` (isolated venv, Python 3.12, mcp 1.30.0) | 0.3.0, stdio, needs `DATABASE_URI`; use `--access-mode unrestricted` to allow write/EXPLAIN during dev |
| Node used by MCP configs | `C:\Users\91454\AppData\Local\Programs\AutoClaw2\resources\vendor\node\node.exe` | v24.20.0 (absolute paths in mcp.json so any client works) |

## MCP wiring (already done)

- `D:\chinatrip\.mcp.json` — project-scoped config for Claude Code (auto-loaded when Claude Code runs in `D:\chinatrip`).
- `mcp/mcp.json` (this folder) — same content, kept as the annotated master copy.
- Servers: `amap-maps`, `sentry`, `postgres`, `dart`.

Credentials are referenced as `${VAR}` placeholders (Claude Code expands env vars). For clients without expansion (e.g. some Cursor versions), replace `${...}` inline or set Windows user env vars:

```powershell
[Environment]::SetEnvironmentVariable('<VARIABLE_NAME from .env.example>','<its value>','User')
```

### Cursor / other clients

Copy the four server blocks from `mcp/mcp.json` into `C:\Users\91454\.cursor\mcp.json` (`mcpServers` key) — same schema.

### Keys still to be supplied (user)

See `mcp/.env.example` — Amap Web-service key, DashScope key, Sentry token, DATABASE_URI, plus Anthropic / OpenAI / Zhipu keys for the LiteLLM fallback chain.

## LiteLLM self-hosted gateway quickstart (W5-8 item, installed early)

```bash
litellm --model dashscope/qwen-plus --port 4000          # single model smoke test
litellm --config litellm_config.yaml --port 4000         # fallback chain:
```

Example fallback chain for `litellm_config.yaml`: `dashscope/qwen-plus` (CN primary) → `gpt-4o` → `claude-sonnet` → `zhipuai/glm-4-plus`; each model entry reads its credential from the matching environment variable named in `.env.example` (DashScope / OpenAI / Anthropic / Zhipu) — see the LiteLLM docs for the exact yaml schema. The vendor Python 3.13 holds litellm 1.105.1 with proxy extras.

## Notes / caveats

- **Disk cleanup (optional, manual):** `D:\dev\flutter_stable.zip` (1.93 GB, SHA already verified) and `D:\dev\clt.zip` (146 MB) can be deleted; the safety guard blocked automated deletion, so do it by hand if D: gets tight.
- **First `flutter` run** rebuilds the pub cache (slow network → a few minutes once); later runs are fast.
- **iOS builds** still need a Mac + Xcode (hardware, not installable here) — unchanged from the gap analysis.
- **Deferred per plan:** Redis MCP and Docker MCP (optional), App Store Connect MCP (doesn't exist), Stripe MCP (out of scope v1.5.1).
- **Skills:** all skills named in the gap analysis were already present (fastapi, playwright-pro, browser-automation, red-team, prompt-engineering, eval, cross-eval, database-schema-designer, sql-database-assistant, chinese-documentation, chinese-commit-conventions, chinese-git-workflow) — nothing to install.
- **Verified final state (flutter doctor):** Flutter 3.47.7 ✓, Android toolchain ✓ (SDK 36.0.0; platforms 35+36, build-tools 35.0.0+36.0.0 installed), Chrome ✓, connected devices ✓, network ✓. Only the Visual Studio check errors (`%PROGRAMFILES(X86)%` not visible in the agent shell) — irrelevant for mobile builds; Windows-desktop targets would need Visual Studio.
- **Dart MCP quirk:** in a stripped environment the server fails with "Could not find the pub cache"; the config therefore pins `LOCALAPPDATA` explicitly in the dart server block.
- **Credentials:** the MCP config intentionally contains no env-placeholder blocks — servers inherit your Windows user environment variables, so set the variables from `.env.example` once at user scope and every client (Claude Code, Cursor, …) picks them up.
