# Self-review — BV-OBS-2

Adds the **dashboard project filter** on top of BV-OBS-1's multi-tenant data layer.
Multi-tenancy is now visible: pick a project → every view (Overview, by-app,
by-prompt, traces) scopes to that tenant; the traces table shows `project_id`.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4 | Filter threaded through all queries; verified scoping (Acme 4/1, Globex 11/2, all 15/3); smoke green. No automated test for the filter callbacks specifically. |
| Sellability vs Grafana/Langfuse | 3.5 | Tenancy is now end-to-end usable (onboard a client → see only their data). Real step up. Still missing: **dashboard auth** (anyone with the URL sees all projects) and quality/judge. |
| Onboarding / UX | 3 | Project → app cascade is intuitive; demo data makes it self-evident. No `prism up` one-command yet; no per-tenant login. |
| Performance & footprint | 4 | Indexed `project_id`; read-only WAL; negligible overhead. |
| Code quality | 4 | Single `_where(project=…)` seam reused everywhere; small surface. |
| Test coverage | 3 | Reused dashboard smoke; multi-tenant ingest covered (BV-OBS-1). Dashboard callback/figure-with-project not unit-tested. |

## Overall verdict: 3.5 / 5
Up from 3.0. The tenancy story now hangs together: keys isolate ingest (BV-OBS-1) and
the dashboard isolates viewing (BV-OBS-2). The glaring gap for a multi-client sale is
**auth** — without a login, project isolation is cosmetic (any viewer can switch
projects). That's the next must-do, alongside the headline quality/judge work.

## Top 3 next actions (feed-forward)
1. **Dashboard auth** — `PRISM_DASHBOARD_PASSWORD` login; optionally per-project
   scoping tokens so a client sees only their project. Closes the tenancy gap.
2. **Second test agent app** on its own project — proves multi-app (not just
   multi-tenant-same-app) and enriches the demo.
3. **LLM-judge + Quality view** — the core differentiator; retire fake safetyRatings.
