# Self-review — BV-OBS-9

Adds **audit / reproducibility** (prod_monitor's hash-logging, native to Prism):
tamper-evident SHA-256 of every LLM input/output, a `/v1/verify` proof endpoint, and
a "reproduction key" surfaced in the dashboard. Directly targets the bank tenants.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4.5 | Hashes computed from FULL text before truncation/redaction; stamped in both capture paths; verify proves match + detects tamper; tested end-to-end + full suite (10) green. |
| Sellability vs Grafana/Langfuse | 4.5 | "Prove exactly what the model produced for this input, and detect tampering" is a compliance feature regulated buyers (banks) actually ask for — neither Grafana nor a generic eval tool gives it out of the box. Strong differentiator with multi-tenancy. |
| Onboarding / UX | 4 | Automatic at capture (no product change); dashboard shows the audit line; `/v1/verify` is a clean API. No CLI verify yet. |
| Performance & footprint | 4.5 | sha256 is negligible; one extra hash per call; stdlib only. |
| Code quality | 4.5 | `audit.py` is a tiny shared seam reused by SDK, collector, and dashboard. |
| Test coverage | 4 | Stamp + verify + tamper covered; verify endpoint covered via TestClient. |

## Overall verdict: 4.5 / 5
The strongest single feature for the target market: tamper-evident, reproducible audit
trail per tenant. Works even when content capture is off (hash without storing text).
Gaps: hashing only covers the user message (not system prompt) in the input hash; no
`prism verify` CLI; and reproduction is only *provable* (hash), not yet *replayable*
(re-run the repro key to regenerate).

## Top 3 next actions (feed-forward)
1. **Include system prompt + params in the input hash** (or a canonical request hash)
   so the reproduction key is complete.
2. **`prism verify` CLI** + a dashboard "verify this text" box for non-API users.
3. **Scheduled evals** (now idempotent + hashed) — the last big operational gap; add
   sampling/budget for judge cost.
