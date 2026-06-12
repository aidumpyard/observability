# Prism — Setup & Integration Guide

LLM observability you can host yourself: **pip-only, no Docker, no SaaS.** One
collector process, one SQLite file, one dashboard. Multi-tenant, with traces,
token/latency metrics, prompt versioning, quality scoring, and tamper-evident audit
hashes.

This guide is three guides in one:

- **Part A — DevOps:** stand up the collector + dashboard.
- **Part B — Developer:** instrument *your* application (worked example: `loan_agent`).
- **Part C — User:** operate it — CLI (projects, prompts, evals, verify) + dashboard.
- **Appendix:** full config reference, troubleshooting, production notes.

---

## Concepts in 60 seconds

| Term | Meaning |
|---|---|
| **Gateway** | Your LLM HTTP endpoint (the `/api/llm/process` contract). Prism treats it as opaque; it never sees your model keys. |
| **SDK** | A thin Python library your app imports. Captures traces and ships them to the collector. Never throws, never blocks. |
| **Collector** | One FastAPI process. The *only* writer to the store. Receives spans/scores over HTTP. |
| **Store** | A single SQLite file (WAL). The collector writes; the dashboard/evals read. |
| **Dashboard** | A Dash/Plotly web app (read-only) for humans. |
| **Project** | A **tenant** (e.g. a client/bank). Identified by an **ingest key**. |
| **App** | An application within a project (e.g. `loan_agent`). |
| **Trace → Spans** | One product interaction = a trace; each LLM call / tool / step = a span. |

```
   your app (SDK)  --HTTPS /v1/ingest-->  COLLECTOR  --writes-->  SQLite
        |                                                            |
   talks to your GATEWAY (LLM)                          DASHBOARD / EVALS (read)
```

---

# Part A — DevOps: deploy the collector + dashboard

### A.1 Prerequisites
- Python **3.10+**, `pip`. That's it. (No Docker, no DB server.)

### A.2 Install
Prism isn't on PyPI yet — install from the source tree. Pick the extras per role:

```bash
# the machine that runs the collector + dashboard:
pip install -e "/path/to/Observability[collector,dashboard,cli,evals]"

# (a product machine only needs the SDK core — see Part B)
```

Extras: `collector` (fastapi+uvicorn) · `dashboard` (dash+plotly+pandas) ·
`cli` (typer) · `langchain` (callback handler) · `evals` (rouge-score) ·
`drift` (bert-score — heavy torch, optional) · `all`.

### A.3 Initialize the store
```bash
prism init --db /var/lib/prism/prism.db        # creates the SQLite schema
```
If you skip this, the collector creates it on first run. Default path is
`~/.prism/prism.db` (override with `--db` or `PRISM_DB`).

### A.4 (Recommended) TLS — no admin rights needed
Spans can contain prompts/responses, so serve the collector over HTTPS. Generate a
self-signed cert in your home dir:

```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout ~/prism/key.pem -out ~/prism/cert.pem \
  -days 825 -subj "/CN=your-host.internal" \
  -addext "subjectAltName=DNS:your-host.internal,IP:10.0.0.5"
```
SDK clients then trust it with `verify="/path/to/cert.pem"` (see B.3).

### A.5 Run the collector
```bash
prism serve \
  --db /var/lib/prism/prism.db \
  --host 0.0.0.0 --port 9100 \
  --ssl-keyfile ~/prism/key.pem --ssl-certfile ~/prism/cert.pem   # omit for HTTP
```
- Runs with **one worker** on purpose — it's the single SQLite writer.
- Enforce keys with `PRISM_REQUIRE_KEY=1` (unknown/missing key → `401`).
- Verify: `curl -k https://localhost:9100/health` →
  `{"status":"ok","schema_version":1,"db":"..."}`.

Collector endpoints: `GET /health` · `POST /v1/ingest` · `POST /v1/scores` ·
`GET /v1/projects` · `POST /v1/verify`.

### A.6 Run the dashboard
```bash
prism dashboard \
  --db /var/lib/prism/prism.db \
  --host 0.0.0.0 --port 8052 \
  --prompts-dir /path/to/your/app/prompts        # optional, enables the Prompts tab
```
Open `http://your-host:8052`. The dashboard is **read-only** and opens a separate
read connection (WAL) — it never blocks the collector.

Dashboard config (env vars, all optional):
```bash
PRISM_IDENTITIES="admin;bank1:<project_id>;bank2:<project_id>"  # see Part C
PRISM_SHOW_WATERFALL=true        # per-trace waterfall (default true)
PRISM_SHOW_QUALITY=true          # Quality tab (default true)
PRISM_SHOW_COST=false            # show cost columns (default false; token-centric)
PRISM_PROMPTS_DIR=/path/to/prompts
```

### A.7 Run it as a long-lived service
`prism serve` / `prism dashboard` are plain processes. Keep them up with whatever you
already use — `systemd --user`, `tmux`/`screen`, `nohup`, `supervisord`. Example
systemd user unit:
```ini
# ~/.config/systemd/user/prism-collector.service
[Service]
ExecStart=%h/.venv/bin/prism serve --db %h/prism/prism.db --port 9100 \
  --ssl-keyfile %h/prism/key.pem --ssl-certfile %h/prism/cert.pem
Restart=always
[Install]
WantedBy=default.target
```
`systemctl --user enable --now prism-collector`.

---

# Part B — Developer: instrument your application

Worked example: **`loan_agent`** (uploads docs → LLM extracts loan features → routes
to one of two LangGraph audits → publishes a decision). Every pattern below is taken
from its real code.

### B.1 Install the SDK (in your app's environment)
```bash
pip install -e "/path/to/Observability"            # SDK core (httpx only)
pip install -e "/path/to/Observability[langchain]" # + LangChain/LangGraph handler
```

### B.2 The golden rule: one LLM seam
Route **every** LLM call through a single function. Prism then instruments your whole
app from one place. In `loan_agent` that seam is `loan_agent/llm_client.py`:

```python
# llm_client.py — the ONLY place that talks to the gateway
import httpx
from .config import settings
from . import obs                      # optional Prism shim (B.4)

def complete(message, *, system_prompt=None, temperature=0.2,
             max_new_token=1024, prompt_id=None) -> str:
    body = {
        "message": message, "system_prompt": system_prompt,
        "model": settings.model, "apiKey": settings.api_key,
        "full_gemini_response": "true",          # ask for full envelope (real tokens)
        "params": {"temperature": temperature, "max_new_token": max_new_token},
    }
    body = {k: v for k, v in body.items() if v is not None}

    def _do():
        r = httpx.post(settings.gateway_url, json=body, timeout=settings.request_timeout)
        r.raise_for_status()
        return r

    # When Prism is enabled this records an llm span (real tokens, prompt ref, hashes)
    # around the call; when disabled it's a passthrough. Either way: the response.
    resp = obs.capture_llm(_do, request=body, model=settings.model, prompt_id=prompt_id)
    return _extract_text(resp.json())
```

`obs.capture_llm(call, request=, model=, prompt_id=)` wraps a callable that returns
an `httpx.Response` (or dict). It records tokens, cost (if enabled), latency,
finish reason, the prompt version, and the audit hashes — **with no change to your
business logic**.

### B.3 Initialize Prism once
```python
import prism
prism.init(
    app="loan_agent",
    endpoint="https://gateway/api/llm/process",     # YOUR LLM gateway
    collector_url="https://prism-host:9100",         # the collector (Part A)
    ingest_key="pk_…",                               # this project's key (Part C.1)
    env="prod",
    app_type="langgraph",
    verify="/path/to/cert.pem",                      # trust the collector's TLS cert
    capture_io=True,                                 # store prompt/response text
    track_cost=False,                                # tokens only (default)
)
# ... run your app ...
prism.shutdown()    # flushes the background queue on exit
```
If `init` is never called, **every Prism call becomes a silent no-op** — your app
runs unchanged.

> **Note on `prism.llm.generate` vs `capture_llm`:** `prism.llm.generate(...)` is a
> ready-made client for the `/api/llm/process` (Gemini) gateway contract — it forces
> `full_gemini_response="true"`, harvests real tokens, and returns the shape you
> asked for. If your endpoint has a *different* shape, wrap your own call with
> `capture_llm` (as above) instead.

### B.4 Make Prism optional (the `obs.py` shim)
So your product still runs when Prism isn't installed, put a thin shim in your app.
This is `loan_agent/obs.py` verbatim — copy it and change the `app=` name:

```python
import contextlib, os
from .config import settings
try:
    import prism
except Exception:                      # Prism not installed -> everything no-ops
    prism = None
_ENABLED = False

def init_from_env() -> bool:
    """Enable Prism if installed and PRISM_ENABLED is truthy."""
    global _ENABLED
    if prism is None or os.environ.get("PRISM_ENABLED","").lower() not in ("1","true","yes"):
        return False
    prism.init(
        app="loan_agent",
        endpoint=settings.gateway_url,
        collector_url=os.environ.get("PRISM_COLLECTOR_URL", "http://127.0.0.1:9100"),
        ingest_key=os.environ.get("PRISM_INGEST_KEY"),
        env=os.environ.get("PRISM_ENV", "dev"),
        app_type="langgraph",
        verify=os.environ.get("PRISM_VERIFY", "true").lower() not in ("0","false","no"),
        track_cost=os.environ.get("PRISM_TRACK_COST", "").lower() in ("1","true","yes"),
    )
    _ENABLED = True
    return True

def enabled():  return _ENABLED
def shutdown(): prism.shutdown() if _ENABLED else None
def trace(name, **kw):  return prism.trace(name, **kw) if _ENABLED else contextlib.nullcontext()
def span(name, kind="span"): return prism.span(name, kind=kind) if _ENABLED else contextlib.nullcontext()
def capture_llm(call, *, request=None, model=None, prompt_id=None):
    return prism.capture_llm(call, request=request, model=model, prompt_id=prompt_id) if _ENABLED else call()
def callbacks():
    if not _ENABLED: return []
    from prism.integrations.langchain import PrismCallbackHandler
    return [PrismCallbackHandler()]
```

### B.5 Open a trace per request
Wrap the top of each user interaction so all spans nest into one trace
(`loan_agent/pipeline.py`):
```python
def run(doc):
    from . import obs
    with obs.trace("loan_process"):
        features = extractor.extract(doc.combined_text)      # -> spans inside
        audit = run_loan_audit(...) or run_loan_audit_esc(...)
        return review.review_and_publish(...)
```

Mark intermediate steps with spans (`loan_agent/extractor.py`):
```python
def extract(text):
    from . import obs, prompts
    p = prompts.get("extract")                                # versioned prompt
    with obs.span("extract", kind="chain"):
        return llm_client.complete_json(text, system_prompt=p.render(), prompt_id=p.ref)
```

### B.6 LangChain / LangGraph: one line
Pass the handler in `config` and every node/tool/LLM call becomes a nested span
(`loan_agent/graphs/loan_audit.py`):
```python
from .. import obs
return dict(_GRAPH.invoke(init, config={"callbacks": obs.callbacks()}))
```

### B.7 Versioned prompts (optional but recommended)
Store prompts as files so you can diff versions and track quality per version. Layout
(`<root>/<app>/<name>/vN.prompt`, frontmatter + body):
```
prompts/loan_agent/extract/v1.prompt
prompts/loan_agent/agent_risk/v1.prompt
```
Load and pass the ref to the LLM call so the span links to the prompt version:
```python
from prism.prompts import PromptRepo
repo = PromptRepo("prompts")
p = repo.load("loan_agent", "extract")        # latest; or load(..., version=2)
text = llm_client.complete(user_msg, system_prompt=p.render(), prompt_id=p.ref)
```

> **Ready-to-run samples:** [`docs/examples/`](examples/) ships a sample prompt repo
> (`support_bot` with a v1/v2 `triage` to demo the diff) and a `golden.json` for
> `prism eval --references`. See [docs/examples/README.md](examples/README.md).

### B.8 Three integration styles (any app, not just loan_agent)
| Your app makes LLM calls via… | Use | Lines changed |
|---|---|---|
| a Gemini-gateway HTTP call | `prism.llm.generate(...)` or `capture_llm(...)` | 1 |
| **LangChain / LangGraph** | `config={"callbacks": [PrismCallbackHandler()]}` | 1 |
| plain business functions | `@prism.observe(kind="tool")` / `with prism.span(...)` | a decorator |

### B.9 Guarantees (why it's safe to leave on)
- **Never throws** into your code (capture errors are swallowed).
- **Never blocks** — the hot path just enqueues; a background thread batches to the
  collector and drops-on-overflow rather than back-pressure your request.
- **Tokens, not dollars,** by default (`track_cost=False`).
- **Audit hashes** (SHA-256 of full input/output) are stamped even if you disable
  text capture (`capture_io=False`) — fingerprint without storing content.

---

# Part C — User: operate it (CLI + dashboard)

### C.1 Create a project (tenant) and get its ingest key
```bash
prism project create "Acme Bank" --db /var/lib/prism/prism.db
# created project 'Acme Bank'
#   project_id : prj_1a2b3c…
#   ingest_key : pk_XXXXXXXX…        <-- give THIS to that client's app (PRISM_INGEST_KEY)

prism project list --db /var/lib/prism/prism.db
```
Each app sends its project's `ingest_key`; the collector stamps `project_id` on every
span **server-side** — so tenants are isolated without any app code change.

### C.2 Browse / inspect prompts
```bash
prism prompts list --root prompts
prism prompts show loan_agent/agent_risk@v2 --root prompts
```

### C.3 Score quality (the eval engine)
Runs heuristics always; add an LLM-judge and/or reference set:
```bash
prism eval \
  --db /var/lib/prism/prism.db \
  --collector http://127.0.0.1:9100 \
  --judge-url https://gateway/api/llm/process \   # optional: LLM-judge (relevance/coherence/safety)
  --references golden.json \                        # optional: ROUGE-L vs expected
  --sample 1.0
```
`golden.json` = `[{"input": "<prompt>", "reference": "<expected output>"}]`. Scores are
**idempotent** (re-running replaces, never duplicates).

**Scheduled evals** — run continuously instead of by hand:
```bash
prism eval --watch --interval 300 \           # every 5 min
  --judge-url https://gateway/api/llm/process \
  --max-judge 200                              # cap judge calls per cycle (cost budget)
```
`--watch` is **incremental**: each cycle re-runs the cheap heuristics but only
LLM-judges **spans not already judged**, so cost stays bounded as data grows. Run it as
a service (systemd/tmux) alongside the collector, or use plain `cron` with the one-shot
form.

### C.4 Verify an output (audit / dispute resolution)
Prove a given text is exactly what a span produced — or detect tampering:
```bash
curl -s -X POST http://127.0.0.1:9100/v1/verify \
  -H 'Content-Type: application/json' \
  -d '{"span_id":"<span_id>","output":"<text to check>"}'
# -> {"match": true, "stored_output_hash":"…", "computed_hash":"…", "model":"…"}
```

### C.5 The dashboard
Open `http://your-host:8052`. Header controls: **identity · project · app · window ·
live**.

- **Identity selector** — driven by `GET /auth/detail`. `PRISM_IDENTITIES="admin;bank1:<prj>;bank2:<prj>"`
  gives `admin` (sees all) and per-tenant logins (`bank1` locked to its project,
  enforced server-side). *Note: this is identity selection, not authentication — put
  an SSO/proxy in front if you need real access control.*
- **Overview** — calls, tokens, latency p50/p95, error rate; calls/tokens over time
  (adaptive granularity); by-app and by-prompt tables.
- **Traces** — click a trace → span table + **Prompts & responses** (collapsible
  System/Prompt/Response, each with a 🔒 audit hash line). Waterfall optional
  (`PRISM_SHOW_WATERFALL`).
- **Quality** — judge scores (relevance/coherence/safety), heuristics, and ROUGE-L
  vs reference, **segregated per project/app/prompt-version**.
- **Prompts** — browse versions, view template, **diff vs previous version**, and
  per-version usage.

---

# End-to-end in 5 commands

```bash
# 1+3. collector AND dashboard in one command (Ctrl-C stops both; add --eval for the loop)
prism up --db ~/prism/prism.db --prompts-dir /path/to/loan_agent/prompts &
#   (equivalently: `prism serve …` and `prism dashboard …` in two terminals)
# 2. a tenant + its key
prism project create "Acme Bank" --db ~/prism/prism.db        # copy the ingest_key
# 4. run your instrumented app, pointed at the collector
PRISM_ENABLED=1 PRISM_COLLECTOR_URL=http://127.0.0.1:9100 \
  PRISM_INGEST_KEY=pk_XXXX python -m loan_agent.cli examples/loan_large.txt
# 5. score quality
prism eval --db ~/prism/prism.db --collector http://127.0.0.1:9100 \
  --judge-url https://gateway/api/llm/process
```
Open `http://localhost:8052` → the loan appears as a trace within ~5s; Quality fills
in after the eval.

---

# Appendix

## Config reference

**SDK — `prism.init(...)`**
| Arg | Default | Meaning |
|---|---|---|
| `app` | — | application name (`app_id`) |
| `endpoint` | — | your LLM gateway URL |
| `collector_url` | — | the Prism collector base URL |
| `ingest_key` | None | this project's key (sent as `X-Prism-Key`) |
| `env` / `app_type` | `dev` / None | tags on every span |
| `data_classification` | `Public` | governance tag |
| `sample_rate` | 1.0 | head sampling (unsampled traces = no-ops) |
| `capture_io` | True | store prompt/response text (hashes still computed) |
| `max_text_chars` | 8000 | truncation cap |
| `redact` | None | `Callable[[str],str]` applied before storage |
| `verify` | True | httpx TLS verify: `True`/`False`/path-to-cert |
| `track_cost` | False | also compute `cost_usd` from the price table |

**App env (loan_agent shim):** `PRISM_ENABLED`, `PRISM_COLLECTOR_URL`,
`PRISM_INGEST_KEY`, `PRISM_ENV`, `PRISM_VERIFY`, `PRISM_TRACK_COST`.

**Collector env:** `PRISM_DB` (store path), `PRISM_REQUIRE_KEY` (strict 401),
`PRISM_INGEST_KEYS` (`project_id:key,…` back-compat).

**Dashboard env:** `PRISM_DB`, `PRISM_IDENTITIES`, `PRISM_SHOW_WATERFALL`,
`PRISM_SHOW_QUALITY`, `PRISM_SHOW_COST`, `PRISM_PROMPTS_DIR`.

**CLI:** `prism init|serve|dashboard|project|prompts|eval`.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Dashboard empty | Widen the **window** to `all`; check the collector is writing the same `--db`. |
| Spans not arriving | Wrong `collector_url`/`ingest_key`; TLS `verify` mismatch (point it at the cert); check `prism.dropped()`. |
| `401` on ingest | `PRISM_REQUIRE_KEY=1` but key unknown — create the project / fix `PRISM_INGEST_KEY`. |
| Quality tab empty | Run `prism eval` first (scores are computed offline). |
| Push/CI of versions | Out of scope here — see repo git setup. |

## Production notes
- **Single writer:** only the collector writes; run it with one worker. Dashboard and
  evals are read-only (WAL). Scores from evals go back through `/v1/scores` — never a
  second direct writer.
- **Scale:** SQLite is comfortable to ~1M spans/day. Past that, the **collector is the
  seam** — swap SQLite for DuckDB/Postgres behind it without touching any app.
- **Privacy:** for non-Public data set `capture_io=False` and/or a `redact` hook —
  you still get tokens, latency, and audit hashes, just not the raw text.
- **Time:** everything is stored in UTC; per-span durations are measured locally, so
  cross-host clock skew never corrupts numbers.
