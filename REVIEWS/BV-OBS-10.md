# Self-review — BV-OBS-10

Adds **scheduled evals**: `prism eval --watch --interval N` runs the eval engine on a
timer, **incrementally** (only judges spans not already judged) with a per-cycle judge
budget. Closes the last big operational gap — quality stays fresh without manual runs.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4.5 | Incremental skip + budget tested; safe because scores are idempotent (BV-OBS-8). Heuristics/reference always run; judge is the only thing gated. |
| Sellability vs Grafana/Langfuse | 4 | "Set it and forget it" continuous quality monitoring is expected of an LLM-obs product; bounded cost makes it operable for small teams. |
| Onboarding / UX | 4 | One flag (`--watch`); documented recipe + cron alternative. No in-dashboard schedule UI (CLI/service only). |
| Performance & footprint | 4.5 | Incremental judging keeps cost ~O(new spans), not O(all spans), each cycle. `--max-judge` hard-caps it. |
| Code quality | 4.5 | Small additions (`judged_span_ids`, `skip_judged`/`max_judge`, `run_loop`); reuses the existing pipeline. |
| Test coverage | 4 | smoke_eval_loop covers incremental + budget; loop itself is a thin wrapper (not separately tested). |

## Overall verdict: 4 / 5
The eval engine is now a real operational capability, not a manual chore: continuous,
incremental, cost-bounded, idempotent. Combined with the judge, ROUGE-L references, and
audit hashes, Prism's quality story is now genuinely competitive.

## Top 3 next actions (feed-forward)
1. **Quality trend over time** — chart judge/ROUGE-L scores by day + a v1-vs-v2 prompt
   delta on the Prompts tab (ties quality changes to prompt changes).
2. **Complete the audit input hash** (system prompt + params, not just user message) +
   a `prism verify` CLI.
3. **`prism up`** — one command to launch collector + dashboard (+ optional eval loop)
   together; the last onboarding-friction item.
