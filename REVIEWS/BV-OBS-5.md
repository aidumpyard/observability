# Self-review — BV-OBS-5

The headline feature: a pluggable **remote LLM-judge** + a **Quality tab**. Prism now
has a real output-quality signal (relevance/coherence/safety, model-graded), not just
operational metrics — and it retires the gateway's synthetic safetyRatings.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4 | Judge + runner + queries tested; judge failures are swallowed per span; scores go through `/v1/scores` (no direct DB write). Judge output depends on a remote model (non-deterministic) — mitigated by temp 0 + clamping. |
| Sellability vs Grafana/Langfuse | 4.5 | This is the differentiator Grafana lacks and the parity item vs Langfuse: quality scoring per prompt-version, scoped per tenant. Combined with multi-tenancy, it's a credible paid offering. |
| Onboarding / UX | 3.5 | Quality tab is clear (cards + by-metric + by-prompt). But evals are run manually (`prism eval`) — no scheduler yet; judge endpoint/model must be configured. |
| Performance & footprint | 4 | Judge is offline/batch, sampled, never on the product path. Each grade = 1 extra LLM call — cost/load is real at scale, so sampling matters (supported, not yet enforced by default). |
| Code quality | 4 | `Judge.score_span` is a clean seam; gateway/OpenAI backends swappable; scores reuse the existing pipeline. |
| Test coverage | 3.5 | Judge unit + dashboard regression; no end-to-end "score → Quality tab renders" automated test (verified manually with 120 demo scores). |

## Overall verdict: 4 / 5
The product now tells you not just *what happened* (RED/cost/traces) but *how good the
output was*, per prompt version and per tenant. That closes the main gap vs Langfuse.
Weak spots: evals are manual (need a scheduler), the judge cost/sampling story should
be a first-class setting, and "is v2 better than v1?" deserves a real trend/compare view.

## Top 3 next actions (feed-forward)
1. **Scheduled evals** — a `prism eval` cron/loop (sampled) so quality stays fresh
   without manual runs; surface judge cost/volume as a budgeted setting.
2. **Prompt quality compare/trend** — chart judge scores over time and a v1-vs-v2
   delta on the Prompts tab (ties quality back to prompt changes).
3. **One-command install** (`prism up`) + quickstart — still the biggest friction to a
   trial/sale.
