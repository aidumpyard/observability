# Self-review — BV-OBS-1

Scope at this version: capture spine + Dash dashboard (Overview/Traces/waterfall/
messages/Prompts) + directory prompt repo + heuristic evals + **multi-tenant (this
cycle)**. Judged against [../SELF_IMPROVE.md](../SELF_IMPROVE.md). Harsh on purpose.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4 | Good smoke/integration coverage; N1/N2 hold; single writer. Caveat: project management writes directly to SQLite (a 2nd writer) — fine because admin-rare + WAL/busy_timeout, but not airtight. No pytest/CI harness. |
| Sellability vs Grafana/Langfuse | 3 | Multi-tenant + keys is a real step (you can now onboard clients on one instance). But **no dashboard auth or project scoping yet**, no LLM-judge/quality, no alerting. A buyer can't safely expose this multi-client. |
| Onboarding / UX | 2 | CLI is decent (`serve`/`dashboard`/`project`/`prompts`) but there's no one-command `prism up`, no quickstart, and the dashboard doesn't filter by project yet — so the new tenancy is invisible to a user. |
| Performance & footprint | 4 | pip-only, SQLite WAL, key-map cached with lazy reload. Comfortable at target scale. |
| Code quality | 4 | Small, modular, consistent; server-side stamping keeps the SDK/product untouched (good seam). |
| Test coverage | 3 | Feature-level smokes are solid; missing: explicit migration-on-existing-DB test, dashboard callback tests, a single `run_all_tests` entry. |

## Overall verdict: 3 / 5
A genuinely solid, honest engineering base, and multi-tenancy moved it from "single-user tool" toward "product." But the **tenancy isn't yet usable end-to-end**: there's no way to *view* a single tenant or to keep tenants from seeing each other in the dashboard, and no auth. That gap is the difference between a demo and something a small client would pay for. The headline "LLM observability" value (quality/judge) is also still heuristic-only.

## Top 3 next actions (feed-forward)
1. **Dashboard project scoping + auth** — project filter across all views + a login
   (`PRISM_DASHBOARD_PASSWORD`). Makes multi-tenancy real and safe to expose.
2. **Second test agent app on its own project** — generates true multi-tenant data so
   the scoping is demonstrable (loan_agent stays frozen).
3. **LLM-judge + Quality view** — pluggable remote judge → `/v1/scores`, a Quality tab,
   retire the fake safetyRatings. This is the core differentiator vs generic APM.
