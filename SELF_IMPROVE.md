# Prism self-improving loop (BV-OBS-Auto)

The autonomous process that runs while the user is away. Each cycle ships one
improvement, **freezes it as a version tag**, then **self-reviews and self-judges**
the whole tool, and feeds the findings into the next cycle. The loop never touches
`BV-OBS-0` (baseline) or `loan_agent` (frozen end product).

## Product stance (think like the PM)
Prism is observability for a **team running multiple LLM/Dash products on one
instance**. Optimize for: multi-tenant isolation (projects + keys), near-zero
integration cost for each product, self-serve onboarding, and a dashboard a
non-expert can read. The bar is "a small client would pay for this instead of
standing up Grafana/Langfuse." Every cycle should move toward that.

## Work schedule (IST) — conservative, to stay under the usage limit
- **Work** every cycle while local time is **before 12:30**.
- **Rest** between **12:30 and 14:30**: finish the current cycle, then DO NOT
  reschedule — the 14:31 cron resumes the loop.
- **Resume** at **14:30** and keep cycling (next stop is the following 12:30).
- Commits/tags accumulate locally (no push until the user fixes GitHub auth).

## The cycle (repeat until roadmap + review backlog are exhausted)

1. **PLAN** — pick the highest-value open item from [AUTO_ROADMAP.md](AUTO_ROADMAP.md).
   If the roadmap is empty, take the top "next action" from the most recent review
   in [REVIEWS/](REVIEWS/).
2. **BUILD** — implement it on `BV-OBS-Auto`. Pip-only/OSS, no Docker. Keep any
   end-product change minimal; `loan_agent` is frozen (build separate test apps).
3. **TEST** — run every smoke/integration test in `.venv`. Must be green. If it
   can't be made green, revert the change. Never tag a red tree.
4. **COMMIT** — one feature per commit, message ends with the Co-Authored-By trailer.
   Append a [WORKLOG.md](WORKLOG.md) entry. Tick the roadmap box. Try `git push`.
5. **FREEZE** — tag the commit `BV-OBS-N` (next integer; BV-OBS-0 is the baseline,
   so the first improvement is `BV-OBS-1`). Tags are immutable once cut.
6. **SELF-REVIEW / JUDGE** — write `REVIEWS/BV-OBS-N.md` using the rubric below:
   score the *whole tool* as it stands at this version, list strengths, weaknesses,
   and the **top 3 next actions**. Be a harsh, honest judge — the goal is a product
   that out-competes Grafana/Langfuse for small clients, not self-congratulation.
7. **FEED FORWARD** — add the review's top next actions to AUTO_ROADMAP.md.
8. **LOOP** — reschedule and start the next cycle.

## Self-judge rubric (score each 1–5, with one line of justification)

| Dimension | What "5" looks like |
|---|---|
| Correctness & reliability | tests cover it; N1 (never throws) / N2 (never blocks) hold; no data loss |
| Sellability vs Grafana/Langfuse | multi-tenant, real feature parity, a clear reason a small client buys this |
| Onboarding / UX | install in one command; dashboard self-explanatory; empty states; docs |
| Performance & footprint | pip-only, SQLite stays within budget; no needless overhead |
| Code quality & maintainability | small, readable, matches house style; seams not coupling |
| Test coverage | the new feature + a regression net; offline + integration |

End each review with: **Overall verdict** (1–5 + one paragraph) and **Top 3 next actions**.

## Versioning
- `BV-OBS-0` — frozen baseline (tag). Never modified.
- `BV-OBS-1`, `BV-OBS-2`, … — frozen improvement snapshots on `BV-OBS-Auto`.
- Review the whole arc: `git log --oneline BV-OBS-0..BV-OBS-Auto`, and the
  per-version self-reviews in `REVIEWS/`.

## Hard limits (be honest with the user)
- The scheduler is **session-scoped** in this environment: the wakeup/cron loop runs
  while the Claude session is alive (incl. the 2:30pm-IST resume), but a hard
  token/usage kill stops it. To resume after that: reopen and say
  "resume BV-OBS-Auto" — the loop picks up from AUTO_ROADMAP.md + REVIEWS/.
- No remote push until GitHub auth is provided (commits + tags accumulate locally).
