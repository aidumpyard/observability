# Self-review — BV-OBS-8

A correctness fix: scores are now **idempotent**. Re-running `prism eval` replaces a
span's score for a metric instead of inserting a duplicate, so Quality averages stay
truthful and evals can be safely scheduled.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4.5 | Upsert on (span_id,name,source) + migration that de-dupes existing rows and adds the unique index. Verified: reruns leave count stable. Edge: trace-level scores (span_id NULL) aren't de-duped (none exist yet) — documented. |
| Sellability vs Grafana/Langfuse | 4 | Trustworthy metrics are table stakes; this removes a credibility bug before scheduled evals. Not a new capability, but a necessary one. |
| Onboarding / UX | 4 | Invisible-but-correct; migration is automatic on connect. |
| Performance & footprint | 4.5 | One unique index; upsert is cheap. |
| Code quality | 4.5 | Small, contained change in db._migrate + writer; reused everywhere scores are written (incl. the eval engine via /v1/scores). |
| Test coverage | 4 | tests/smoke_idempotent.py covers replace + coexistence; full suite (9) green. |

## Overall verdict: 4 / 5
Unblocks scheduled evals and makes the Quality page honest under reruns — the right
thing to fix before adding more eval surface. No new product capability, hence not a 5.

## Top 3 next actions (feed-forward)
1. **Audit hash on spans** (prod_monitor idea) — stamp output_hash at capture + a
   `verify` view; cheap, tamper-evident, high-value for bank tenants.
2. **Scheduled evals** — now safe to run on a timer/cron (idempotent); add sampling +
   a budget so judge cost is bounded.
3. **Demo-data hygiene** — give chart-seed spans responses (or exclude from scoring)
   so the demo "answered" rate isn't artificially low.
