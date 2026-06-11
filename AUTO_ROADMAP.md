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

## Roadmap (in priority order)
- [ ] **Phase 3 — Eval engine**: heuristic scorers (latency-SLO, token-budget,
      empty/refusal, json-valid, length) → POST `/v1/scores`. *(started)*
- [ ] Pluggable remote **LLM-judge** (Gateway/OpenAI-compatible) → quality scores;
      tagged `internal=eval`, retires the fake safetyRatings.
- [ ] Dashboard **Quality view**: scores per app / per prompt-version + trends.
- [ ] **Self-observability**: surface SDK `dropped` spans counter in the dashboard.
- [ ] **Retention** (Phase 5): configurable max-age cleanup + VACUUM; `prism gc`.
- [ ] Prompt repo: optional **version pinning** ("production" pointer) so adding a
      new version doesn't auto-promote.
- [ ] **OTel `gen_ai.*` export** option from the collector.
- [ ] Docs: fold cost=opt-in, Dash, prompt repo, evals into ARCHITECTURE.md.
- [ ] Test hardening + a top-level `make test` / `run_all_tests.sh`.

## How to review when back
`git log --oneline BV-OBS-0..BV-OBS-Auto` shows everything done autonomously.
`git diff BV-OBS-0..BV-OBS-Auto` is the full delta. Revert any commit you dislike;
the baseline is safe at the `BV-OBS-0` tag.
