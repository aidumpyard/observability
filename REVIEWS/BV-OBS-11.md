# Self-review — BV-OBS-11

Adds **`prism up`** — one command launches the collector + dashboard (+ optional
`--eval` loop) and tears them down cleanly on Ctrl-C. The last onboarding-friction
item the reviews kept flagging.

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4 | Subprocess supervision: prints URLs, exits if a child dies, terminates the tree on signal. Tested launch + clean teardown. Edge: relies on the same `sys.executable`/CLI being importable (fine for an installed package). |
| Sellability vs Grafana/Langfuse | 4 | "pip install → `prism up` → open the dashboard" is the 60-second trial that turns a curious dev into a user. Frictionless trial = sales. |
| Onboarding / UX | 4.5 | Collapses 2–3 commands into one; README + guide now lead with it; `--eval` wires continuous quality too. |
| Performance & footprint | 4.5 | Just supervises existing processes; no new deps (stdlib subprocess/signal). |
| Code quality | 4 | Contained in `cmd_up`; reuses the existing `serve`/`dashboard`/`eval` CLIs rather than duplicating server logic. |
| Test coverage | 4 | smoke_up launches the real stack on test ports, verifies both endpoints, and asserts clean teardown. |

## Overall verdict: 4 / 5
Small but high-leverage: it makes everything built so far trivially demoable, which is
exactly what a sellable product needs. Not a new capability, but the one that lowers the
barrier to all the others.

## Top 3 next actions (feed-forward)
1. **Quality trend over time** + v1-vs-v2 prompt delta on the Prompts tab — the most
   visible remaining product feature (uses judge/ROUGE-L data we already store).
2. **Complete the audit input hash** (system prompt + params) + a `prism verify` CLI /
   dashboard verify box.
3. **Retention / `prism gc`** — configurable max-age cleanup + VACUUM, so the store
   doesn't grow unbounded once evals run continuously.
