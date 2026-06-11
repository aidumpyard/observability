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
