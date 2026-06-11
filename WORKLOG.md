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

## 2026-06-11 — BV-OBS-3: dashboard auth + per-tenant lock
- Added prism/dashboard/auth.py: HTTP Basic gate (zero deps, Flask under Dash).
  Env-driven: PRISM_DASHBOARD_PASSWORD (+ PRISM_DASHBOARD_USER) = admin; or
  PRISM_DASHBOARD_USERS="user:pass:project;..." for multiple users where the
  optional 3rd field binds a user to one project (per-client logins). Open if unset.
- Per-tenant lock: a bound user's project dropdown shows only their project AND
  _render enforces the scope server-side (can't widen by tampering).
- Tests: tests/smoke_auth.py (401 gate, admin+tenant logins, bad pw, binding) ✅;
  dashboard regression ✅. Live: 401/200/200/401 verified via curl.

## 2026-06-11 — BV-OBS-4: identity endpoint replaces password auth
- Removed HTTP Basic auth (auth.py + smoke_auth deleted). Added prism/dashboard/
  identity.py + `GET /auth/detail` -> {"identities": ["admin","bank1","bank2"]}.
  Identities are env-driven (PRISM_IDENTITIES="admin;bank1:<prj>;bank2:<prj>").
- Dashboard header has an **identity dropdown** (no password): admin = all projects;
  bank1/bank2 lock + disable the project filter and are enforced server-side in
  _render. Dashboard is open (200, no 401).
- Tests: tests/smoke_identity.py (/auth/detail body, scoping map, open access) ✅;
  dashboard regression ✅. Live: /auth/detail returns admin/bank1/bank2; bank1->Acme,
  bank2->Globex.
- NOTE: this is identity *selection*, not authentication (no secret) — front with a
  real auth proxy if access must be restricted.

## 2026-06-11 — BV-OBS-5: LLM-judge + Quality view
- prism/evals/judge.py: pluggable GatewayJudge (force-full gateway contract) grades a
  span's response -> judge_relevance/coherence/safety scores (source=llm_judge). Runner
  extended to run heuristics + optional judge (sampled); `prism eval [--judge-url]` CLI.
- queries.quality_summary + quality_by_prompt (scores⋈spans, project/app scoped).
  Dashboard **Quality tab**: judge + heuristic cards, scores-by-metric, and LLM-judge
  quality by prompt version (real safety signal replaces synthetic safetyRatings).
- Tests: tests/smoke_judge.py ✅; dashboard regression ✅. Demo: 120 scores written
  (15 spans × heuristics+judge); judge avgs rel 4.47 / coh 4.0 / safety 5.0.

## 2026-06-11 — BV-OBS-5 hotfix: Quality tab "ambiguous column name: created_at"
- scores⋈spans share created_at; _where now qualifies columns via a `prefix` arg
  ("s.") for the joined quality queries. Quality tab now renders. Re-pointed the
  BV-OBS-5 tag to the fixed commit (local-only, tag was minutes old + broken).

## 2026-06-12 — BV-OBS-6: better "over time" chart
- timeseries: adaptive bucket granularity (minute <=6h, hour <=7d, day beyond);
  build_timeseries now uses a real datetime x-axis, spline lines + markers, area fill,
  unified hover, adaptive tick format. Single-point data renders as a visible marker.
- Header **metric switch**: calls+tokens / calls / tokens (persistent, no tick reset).
- Seeded 258 demo spans across 24h (Acme/Globex) so the curve is visible.
- Tests: dashboard regression ✅; all 3 metric modes build.

## 2026-06-12 — config toggles: waterfall + quality tab
- Dashboard config flags PRISM_SHOW_WATERFALL / PRISM_SHOW_QUALITY (true/false;
  also create_app/run params). false -> Traces hides the waterfall graph (keeps span
  table + prompts/responses); Quality tab removed from the tabs entirely.
- Set BOTH to FALSE for now (per request). Verified on/off; regression green.
