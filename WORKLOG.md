# BV-OBS-Auto worklog

Newest first. Each entry: what changed, why, how verified. Baseline = `BV-OBS-0`.

## 2026-06-11 — versioning + autonomous setup
- Initialized git, committed the **BV-OBS-0** baseline, tagged it, branched
  **BV-OBS-Auto**. Added `.gitignore`, [AUTO_ROADMAP.md](AUTO_ROADMAP.md), this log.
- Remote `origin` = https://github.com/aidumpyard/observability.git (push target for
  autonomous work). loan_agent remains a separate local repo (same BV-OBS-0 /
  BV-OBS-Auto scheme).
- Verified: `git log`, tag + branch present.

## 2026-06-11 — push blocked (credentials)
- `git push` to origin failed: no gh CLI, no SSH key, no stored PAT (osxkeychain
  empty for github.com). Remote stays configured; autonomous commits accumulate on
  BV-OBS-Auto locally. To enable push: `gh auth login` OR add an SSH key OR store a
  PAT. Will push on next change once auth is present.

## 2026-06-11 — Phase 3: eval engine (heuristics)
- Added `prism/evals/`: heuristic scorers (latency_slo, token_budget,
  empty_or_refusal, json_valid, response_length) + a runner that reads spans
  read-only and submits scores via collector `/v1/scores` (never a direct writer).
- Tests: `tests/smoke_evals.py` (all scorers) ✅; spine regression ✅.
- Next: pluggable remote LLM-judge, then dashboard Quality view.

## 2026-06-11 — BV-OBS-Auto authority + priorities set
- User granted: run code/tests/servers, commit to BV-OBS-Auto, install OSS pip deps,
  edit Prism freely. **loan_agent FROZEN.** Build a separate 2nd test app.
- #1 priority: **multi-tenant + API keys/auth** (sell to small clients vs Grafana/Langfuse).
- Added `.claude/settings.json` allowlist (python/pytest/pip/git/uvicorn/curl) to
  reduce approval prompts during autonomous runs.
- Re-pointed roadmap accordingly.
- Scheduling: in-session wakeup loop + a 2:31pm-IST one-shot resume. NOTE: scheduler
  is session-scoped here (durable flag not honored) — a hard token-limit kill stops
  auto-resume; user must reopen and say "resume BV-OBS-Auto".

## 2026-06-11 — self-improving versioned loop defined
- Added SELF_IMPROVE.md: each cycle ships one improvement, freezes a version tag
  (BV-OBS-1, BV-OBS-2, ...), then self-reviews/judges the whole tool against a
  rubric and feeds the top next-actions back into the roadmap.
- Added REVIEWS/ (one self-review per version). Roadmap references the process.
- Dashboard confirmed live on :8052 (HTTP 200).

## 2026-06-11 — work schedule + PM stance
- Work-hours policy added to SELF_IMPROVE.md: cycle until 13:00 IST, rest 13:00–14:30,
  resume 14:30 (cron). Commit-only (no push) until git auth fixed; stack versions
  locally for a bulk push later.
- PM stance: multi-tenant, low-integration-cost observability for a team running
  multiple products; bar = "a small client buys this over Grafana/Langfuse."

## 2026-06-11 — BV-OBS-1: multi-tenant + API keys
- `projects` table + per-project ingest keys; collector resolves `X-Prism-Key` ->
  `project_id` and stamps it on spans **server-side** (no SDK/product change);
  strict mode (`PRISM_REQUIRE_KEY=1`) returns 401 for unknown/missing keys; open dev
  mode otherwise. `prism project create/list` CLI; `GET /v1/projects`. Additive
  migration adds `project_id` to existing DBs.
- Tests: tests/smoke_multitenant.py (2 tenants, stamping, 401, isolation) ✅;
  CLI create/list ✅; spine regression ✅.
- Froze tag BV-OBS-1. Next: dashboard project filter/scoping + project-aware queries.

## 2026-06-11 — autonomy paused (back to non-autonomous)
- Per user: no-prompt bypass mode is opt-in only via "claude go autonomous mode".
  Reverted settings.local.json to normal prompting; settings.json back to the named
  allowlist (no bypass). Saved .claude/settings.autonomous.json as the opt-in template.
- Cancelled the unattended jobs (12:05 cycle + 2:31pm resume). Loop paused; nothing
  runs without the user. BV-OBS-1 remains frozen.

## 2026-06-11 — BV-OBS-2: dashboard project filter (multi-tenant visible)
- Added a "project" filter dropdown to the dashboard header; threaded `project`
  through all queries (overview/timeseries/by_app/by_model/by_prompt/recent_traces)
  + `list_projects` (names from projects table). App dropdown scopes to the selected
  project; traces table shows `project_id`. Multi-tenancy is now visible in the UI.
- Demo data: 2 projects (Acme Bank, Globex Capital) via loan_agent runs with per-
  project keys (loan_agent untouched, env only). Verified scoping: Acme 4 calls/1
  trace, Globex 11/2, all 15/3.
- Tests: dashboard smoke ✅; live dashboard HTTP 200. Built interactively (non-auto).
- NOTE: dashboard *auth* (login) still pending — filter only.
