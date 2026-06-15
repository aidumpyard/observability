# Self-review — BV-OBS-7

Adds **reference-based quality** (ROUGE-L) from the dev_check/prod_monitor toolkit,
complementing the reference-free LLM-judge. Plus this session's dashboard config
toggles and Traces/chart fixes.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4 | ROUGE-L verdicts + input-hash matching tested; integrates via the existing scores pipeline. Caveat: re-running `prism eval` duplicates scores (no idempotency). |
| Sellability vs Grafana/Langfuse | 4 | Now offers *both* paradigms: reference-free judge (live traffic) and reference-based regression (golden set) — that breadth is a real selling point. BERTScore drift still pending. |
| Onboarding / UX | 3.5 | `prism eval --references file.json` is clean and the dev_check input-hash model is intuitive; but there's no golden-set authoring UI and refs are a hand-written file. |
| Performance & footprint | 4.5 | rouge-score is pure-python/light; the heavy BERTScore is correctly quarantined to an optional `drift` extra (not installed/run). |
| Code quality | 4 | `reference.py` is a tidy seam (rouge_l + sha256 + load + score_span); reused everywhere. |
| Test coverage | 3.5 | reference scorer unit-tested; no end-to-end "refs -> Quality card" automated test (verified manually, avg 0.64). |

## Overall verdict: 4 / 5
Good strategic add: Prism can now answer "did this output regress vs a known-good
reference?" cheaply, not just "is it good in isolation." The honest gaps: (1) **score
idempotency** — eval reruns pile up duplicate scores and skew averages; (2) **golden-set
management** is a raw JSON file, not a first-class store; (3) **audit hashing** (the
prod_monitor reproducibility idea — great for the bank tenants) and **BERTScore drift**
are designed-for but not yet built.

## Top 3 next actions (feed-forward)
1. **Eval idempotency** — upsert scores by (span_id, name, source) so reruns replace
   rather than duplicate. Important before evals are scheduled.
2. **Audit hash on spans** — stamp output_hash at capture + a `verify` view; cheap,
   tamper-evident, high-value for bank tenants (prod_monitor's hash-logging).
3. **Golden eval-set store + BERTScore (optional `drift` extra)** — manage references
   as data, add semantic-drift trend for teams that accept the torch dependency.
