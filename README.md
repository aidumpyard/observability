# Prism — self-hosted LLM observability

Pip-only, zero-infra (no Docker, no SaaS) observability for apps built on an
`/api/llm/process`-style LLM gateway. One collector process + one SQLite file + one
dashboard. **Multi-tenant**, with end-to-end traces, token/latency metrics, a
versioned prompt repo, quality scoring (heuristics + LLM-judge + ROUGE-L), and
**tamper-evident audit hashes**.

```
 your app (SDK)  --/v1/ingest-->  collector  --writes-->  SQLite  <--reads--  dashboard / evals
      |
 talks to your LLM gateway
```

## Quick start
```bash
pip install -e ".[collector,dashboard,cli,evals]"
prism up --db ~/prism/prism.db                           # collector + dashboard in one command
prism project create "Acme Bank" --db ~/prism/prism.db   # -> ingest key for a tenant
```
`prism up` launches the collector (:9100) and dashboard (:8052) together (add `--eval`
for a continuous eval loop); Ctrl-C stops both. Or run them separately with
`prism serve` / `prism dashboard`.
Then instrument your app and point it at the collector. **Full step-by-step (DevOps +
Developer + User):** [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

## In your app (3 lines)
```python
import prism
prism.init(app="myapp", endpoint="https://gw/api/llm/process",
           collector_url="https://prism:9100", ingest_key="pk_…")
with prism.trace("handle_request"):
    resp = prism.llm.generate(message="…", model="gemini-2.5-flash")
```
Works with raw HTTP, **LangChain/LangGraph** (`PrismCallbackHandler`), or plain
functions (`@prism.observe`). Never throws into your code, never blocks the request.

## What's inside
- `prism/` — SDK, collector, store, dashboard (Dash/Plotly), evals, prompt repo, audit.
- `docs/GETTING_STARTED.md` — the complete guide.
- `ARCHITECTURE.md` — design & decisions. `REVIEWS/` — per-version self-reviews.

## Docs
- **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)** — hands-on: run the services locally + instrument your app (the SDK functions).
- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) — full DevOps + Developer + User guide.
- [ARCHITECTURE.md](ARCHITECTURE.md) · [SDK.md](SDK.md) — design & decisions.

Versions are tagged `BV-OBS-N` on the `BV-OBS-Auto` branch, each with a self-review in
[`REVIEWS/`](REVIEWS/).
