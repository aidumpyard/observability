# Self-review — BV-OBS-12

Driven by building a **Dash frontend for loan_agent**, which immediately exposed a real
gap: Prism took `user_id`/`session_id` on the trace but **never persisted them**. Fixed
that, added `current_trace_id()`, and a dashboard **deep-link** (`?trace=<id>`) so an app
can link a request straight to its trace.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4.5 | user/session stamped from trace context at emit; additive migration; verified end-to-end (12 spans all carry the user). Full suite (12) green. |
| Sellability vs Grafana/Langfuse | 4.5 | Per-end-user attribution + "open this exact run in the dashboard" is what product teams expect (Langfuse parity); the frontend makes the value tangible in a demo. |
| Onboarding / UX | 4 | The loan_agent frontend is a real, clickable demo that links to Prism. Dashboard now has a `user_id` column. No by-user *filter* yet. |
| Performance & footprint | 4.5 | Two nullable columns + a contextvar read at emit; trivial. |
| Code quality | 4 | Clean stamping seam in `_emit`; deep-link folded into the existing select callback (no duplicate outputs). |
| Test coverage | 4 | End-to-end user-trace verified; deep-link callback exercised via the app build (no browser test). |

## Overall verdict: 4.5 / 5
The "instrument a real frontend" exercise paid off exactly as intended — it found a
genuine missing capability (end-user identity) and a useful one (deep-link), both now
shipped. Prism now ties **tenant → user → session → trace → span → LLM call**.

## Gaps this exercise surfaced (next)
1. **By-user / by-session filter** in the dashboard (column exists; filter doesn't).
2. **Errors surfaced to the end user** + a live tail of one session.
3. **Cross-process `PrismASGIMiddleware`** — not needed for the in-process frontend, but
   the moment loan_agent's frontend talks to its FastAPI backend over HTTP, we'll want
   `traceparent` auto-continuation. Designed in SDK.md; not yet built.
4. **Latency/quality shown back to the user** (the frontend could display the run's
   tokens/latency, read from the trace).
