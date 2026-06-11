# BV-OBS-Auto — autonomous work plan

This branch holds changes made autonomously while the user is away. The
**BV-OBS-0** tag is the frozen baseline; never modify it.

## Guardrails (must hold for every change)
1. **Branch isolation** — commit ONLY to `BV-OBS-Auto`. Never commit to the default
   branch, never move/retag `BV-OBS-0`. No pushing (no remote configured).
2. **Green before commit** — run the relevant smoke/integration tests; commit only
   when they pass. If a change can't be made green, revert it.
3. **One feature per commit**, clear message, `Co-Authored-By: Claude Opus 4.8`.
4. **Append to [WORKLOG.md](WORKLOG.md)** after each commit (what + why + tests).
5. **No destructive/outward-facing actions.** Local only. Keep the running
   dashboard/collector demos working.
6. Stop when the roadmap is exhausted or a task is genuinely blocked (record why).

## Roadmap (priority order — updated 2026-06-11, BV-OBS-Auto judge call)
GOAL: sellable to small clients, competing with Grafana/Langfuse.
RULE: **loan_agent is FROZEN** — never modify it. Build a *separate* second test app.

- [ ] **Multi-tenant + API keys/auth (#1, sellable)**: `projects` table + per-project
      ingest keys; collector resolves `X-Prism-Key` → project_id and stamps it on
      spans (server-side, no SDK/product change); `prism project create/list` CLI;
      strict mode rejects unknown keys.
- [ ] **Second test agent app** (new project — e.g. support/invoice triage), wired to
      Prism with its own project key → real multi-app/multi-tenant view.
- [ ] **Dashboard auth + project scoping**: login (PRISM_DASHBOARD_PASSWORD), project
      filter, per-project views.
- [x] Phase 3 eval engine — heuristic scorers (done).
- [ ] Pluggable remote **LLM-judge** → `/v1/scores` (retires fake safetyRatings).
- [ ] Dashboard **Quality view**: scores per app / per prompt-version + trends.
- [ ] **Self-observability**: SDK `dropped` spans meter in the dashboard.
- [ ] **Retention** (`prism gc`): max-age cleanup + VACUUM.
- [ ] Prompt repo: **version pinning** ("production" pointer).
- [ ] **OTel `gen_ai.*` export** from the collector.
- [ ] **One-command install**: `prism up` (collector+dashboard) + quickstart docs.
- [ ] Docs: fold cost-opt-in, Dash, prompt repo, evals, multi-tenant into ARCHITECTURE.md.
- [ ] Test hardening + `run_all_tests.sh`.

## How to review when back
`git log --oneline BV-OBS-0..BV-OBS-Auto` shows everything done autonomously.
`git diff BV-OBS-0..BV-OBS-Auto` is the full delta. Revert any commit you dislike;
the baseline is safe at the `BV-OBS-0` tag.
