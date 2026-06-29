# Prism — Run-From-Source & New-App Integration Guide

A self-contained runbook for a **new machine** that wants to (1) understand Prism,
(2) **run it without installing the `prism` package** (run straight from this
source tree), and (3) **wire a brand-new application** into it.

> If you prefer the install-based path and the full conceptual tour, see
> [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md). This guide is the
> no-install, "just start it" version.

---

## 1. What Prism is (60-second model)

Prism is **pip-only, zero-infra LLM observability**: one collector process, one
SQLite file, one dashboard. Your application sends *traces* (one per request) made
of *spans* (each LLM call / tool / step) to the collector; the dashboard reads them.

| Piece | What it is |
|---|---|
| **Gateway** | *Your* LLM HTTP endpoint — the `/api/llm/process` contract. Prism treats it as opaque and never sees your model keys. |
| **SDK** | A thin Python library your app imports (core dep: `httpx`). Captures traces, ships them to the collector. **Never throws into your code, never blocks** the request path. |
| **Collector** | One FastAPI process — the *only* writer to the store. Receives spans/scores over HTTP. |
| **Store** | A single SQLite file (WAL). Collector writes; dashboard/evals read. |
| **Dashboard** | A read-only Dash/Plotly web app for humans. |
| **Project** | A tenant (e.g. a client). Identified by an **ingest key** (`pk_…`). |

```
   your NEW app (SDK)  --HTTP /v1/ingest-->  COLLECTOR  --writes-->  SQLite
        |                                                              |
   calls your GATEWAY (LLM, /api/llm/process)              DASHBOARD / EVALS (read)
```

**Key fact:** Prism never calls the LLM. Your app calls the gateway; Prism only
*observes* that call. The request shape is the same Gemini-gateway contract
(`message`, `system_prompt`, `model`, `apiKey`, `full_gemini_response`, `params`).

---

## 2. Run Prism WITHOUT installing it

We do **not** `pip install` the `prism` package. We install only the third-party
libraries it needs, put the source tree on `PYTHONPATH`, and invoke the CLI as a
module: `python -m prism.cli ...`.

### 2.1 Prerequisites
- **Python 3.10+** and `pip`.
- This repository on disk (clone or unzip). We'll call its root `$PRISM` — the
  folder containing `pyproject.toml` and the `prism/` package.

### 2.2 One-time setup
```bash
cd "$PRISM"                       # repo root (has pyproject.toml)
python3 -m venv .venv
source .venv/bin/activate         # Windows cmd: .venv\Scripts\activate.bat
                                  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install "httpx>=0.27" "fastapi>=0.110" "uvicorn>=0.29" \
            "dash>=2.16" "plotly>=5.20" "pandas>=2.2" \
            "typer>=0.12" "rouge-score>=0.1.2"
export PYTHONPATH="$PRISM"        # Windows cmd: set PYTHONPATH=C:\path\to\prism
```
> `PYTHONPATH` makes `import prism` and `python -m prism.cli` resolve to this source
> tree. Set it once per terminal. The `prism` CLI command does **not** exist (we
> never installed the package) — always use `python -m prism.cli`.

### 2.3 Start the collector (terminal 1)
```bash
mkdir -p ~/prism
python -m prism.cli serve --db ~/prism/prism.db --port 9100
# verify (another terminal):  curl -s http://127.0.0.1:9100/health
```
Runs with one worker on purpose — it's the single SQLite writer.

### 2.4 Start the dashboard (terminal 2)
```bash
export PYTHONPATH="$PRISM"
python -m prism.cli dashboard --db ~/prism/prism.db --port 8052 \
  --prompts-dir /path/to/your_app/prompts          # --prompts-dir optional
# open http://127.0.0.1:8052
```
Optional dashboard env vars: `PRISM_IDENTITIES="admin;bank1:<prj>;bank2:<prj>"`,
`PRISM_SHOW_WATERFALL`, `PRISM_SHOW_QUALITY`, `PRISM_SHOW_COST`.

### 2.5 Create a tenant and get its ingest key
```bash
python -m prism.cli project create "Acme Bank" --db ~/prism/prism.db
#   project_id : prj_…        <- used for dashboard identities
#   ingest_key : pk_…         <- give THIS to the app (PRISM_INGEST_KEY)
python -m prism.cli project list --db ~/prism/prism.db
```

> **Windows:** replace `python -m prism.cli` everywhere as-is (it works on Windows),
> set env vars with `set NAME=value` (cmd) or `$env:NAME="value"` (PowerShell), and
> open each long-running process (`serve`, `dashboard`) in its **own** window with
> `PYTHONPATH` set.

---

## 3. Integrate a NEW application

This is what you change **in your app**. It's ~4 touch points. Your app also runs
from source against Prism (no install): in the app's environment install `httpx`
(and `langchain-core` only if you use LangChain), and set
`PYTHONPATH=$PRISM` so `import prism` resolves.

```bash
# in the NEW app's environment:
pip install "httpx>=0.27"            # + "langchain-core>=0.2" if you use LangChain
export PYTHONPATH="$PRISM"           # the Observability repo root
```

### 3.1 The four touch points

**(1) Initialize once at startup**
```python
import prism
prism.init(
    app="your_app",                                  # -> app_id on every span
    endpoint="https://your-gateway/api/llm/process", # YOUR real LLM gateway
    api_key="<gateway key>",                         # forwarded to the gateway as "apiKey"
    collector_url="http://127.0.0.1:9100",           # the Prism collector
    ingest_key="pk_…",                               # this tenant's key
    env="prod", app_type="langgraph",                # tags; app_type optional
    capture_io=True,                                 # store prompt/response text (hashes always on)
    track_cost=False, verify=True,                   # tokens-only; TLS True/False/path
)
# ... run the app ...
prism.shutdown()                                     # flush the background queue on exit
```
If `init` is never called, **every Prism call is a silent no-op** — the app runs
unchanged.

**(2) Open a trace per request — set `user_id` and `session_id` here**
```python
with prism.trace("checkout", user_id=current_user, session_id=conversation_id):
    ...  # every span inside nests into this trace and inherits user/session
```
> This is the important one. `user_id`/`session_id` flow to every span in the trace
> and drive the dashboard's **user filter** and **session column**. Omit them and
> the app still works, but those views are blank.

**(3) Route LLM calls through the SDK** — pick what matches your app:

| Your app calls the LLM via… | Change |
|---|---|
| an existing Gemini-gateway HTTP call | wrap it: `prism.capture_llm(call, request=, model=, prompt_id=)` |
| nothing yet (let the SDK call it) | `prism.llm.generate(message, system_prompt=, model=, prompt_id=)` |
| **LangChain / LangGraph** | `config={"callbacks": [PrismCallbackHandler()]}` |
| plain business functions | `@prism.observe(kind="tool")` or `with prism.span("step", kind="chain"):` |

```python
# (a) wrap an EXISTING httpx call — Prism never touches your gateway key here:
def complete(message, system_prompt, prompt_id=None):
    body = {"message": message, "system_prompt": system_prompt,
            "model": "gemini-2.5-flash", "full_gemini_response": "true"}
    def _do():
        r = httpx.post(GATEWAY, json=body, timeout=30); r.raise_for_status(); return r
    resp = prism.capture_llm(_do, request=body, model="gemini-2.5-flash", prompt_id=prompt_id)
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

# (b) OR let the SDK make the call (it forwards api_key and harvests tokens):
text = prism.llm.generate(message=msg, system_prompt=sys,
                          model="gemini-2.5-flash", prompt_id="your_app/extract@v1")

# (c) LangChain / LangGraph — one line:
from prism.integrations.langchain import PrismCallbackHandler
result = graph.invoke(state, config={"callbacks": [PrismCallbackHandler()]})
```

**(4) `prism.shutdown()` on exit** (already shown in step 1) — flushes the queue.

### 3.2 Minimal before → after

```diff
+ import prism
+ prism.init(app="your_app", endpoint=GATEWAY, api_key=KEY,
+            collector_url="http://127.0.0.1:9100", ingest_key="pk_…")

  def handle_request(req):
-     result = run_pipeline(req)
+     with prism.trace("request", user_id=req.user, session_id=req.session):
+         result = run_pipeline(req)      # LLM calls inside use capture_llm / llm.generate
      return result

+ # at process shutdown:
+ prism.shutdown()
```

### 3.3 Optional: make Prism fully optional (the `obs.py` shim)
So your product still runs when Prism isn't present, route through a thin shim that
no-ops unless `PRISM_ENABLED` is set. Then turning Prism on is purely env config —
no code change. Full shim source: [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) §B.4.
```bash
export PRISM_ENABLED=1
export PRISM_COLLECTOR_URL=http://127.0.0.1:9100
export PRISM_INGEST_KEY=pk_…
# also read: PRISM_ENV, PRISM_VERIFY, PRISM_TRACK_COST
```

---

## 4. The LLM gateway: demo vs production

Prism posts to whatever you set as `endpoint`. **The contract is always
`/api/llm/process`** — only the URL changes between demo and production.

| | `endpoint` | `api_key` | Who answers |
|---|---|---|---|
| **Demo** | `http://127.0.0.1:8400/api/llm/process` | none | `scripts/demo/fake_gw.py` (canned, token-shaped responses — no keys, no cost) |
| **Production** | `https://your-gateway/api/llm/process` | your real key | your real Gemini-backed gateway |

**Two keys — don't confuse them:**
- **`api_key`** → your **gateway/LLM** key, sent to the gateway as `"apiKey"`.
- **`ingest_key`** (`pk_…`) → your **Prism collector** key; identifies the tenant.
  Nothing to do with the LLM.

---

## 5. Quality scoring (optional)

Heuristic scores run offline (no LLM). An LLM-**judge** (relevance/coherence/safety)
needs an endpoint speaking the same `/api/llm/process` contract.
```bash
# heuristics only (offline):
python -m prism.cli eval --db ~/prism/prism.db --collector http://127.0.0.1:9100 --sample 1.0

# + LLM-judge (point at a real LLM, or local Ollama, or scripts/demo for a fake judge):
python -m prism.cli eval --db ~/prism/prism.db --collector http://127.0.0.1:9100 \
  --judge-url https://your-gateway/api/llm/process --judge-model gemini-2.5-flash \
  --max-judge 200            # cap judge calls per run (cost budget)
```
Scores are **idempotent** (re-running replaces, never duplicates).

---

## 6. See it populated fast (demo data)

The repo ships demo helpers under [`scripts/demo/`](scripts/demo/) so you can fill a
dashboard with no API keys. With the collector already running on `:9100`:
```bash
python scripts/demo/fake_gw.py &                                   # fake gateway :8400
python -m prism.cli project create "Acme Bank" --db ~/prism/prism.db   # copy the pk_ key
KEY=<pk_…> USERS="alice,bob,carol" N=21 SEED=1 python scripts/demo/seed.py
python -m prism.cli eval --db ~/prism/prism.db --collector http://127.0.0.1:9100 --sample 1.0
```
See [`scripts/demo/README.md`](scripts/demo/README.md) for details.

---

## 7. Verify

```bash
curl -s http://127.0.0.1:9100/health        # {"status":"ok",...}
# run the smoke suite (from repo root, PYTHONPATH set):
for t in tests/smoke_*.py; do python3 "$t" >/dev/null 2>&1 && echo "PASS $t" || echo "FAIL $t"; done
# open the dashboard:
#   http://127.0.0.1:8052   (widen the window to "all" if it looks empty)
```

---

## Reference

**Ports (defaults):** collector `9100` · dashboard `8052` · demo gateway `8400`.

**Collector HTTP:** `GET /health` · `POST /v1/ingest` · `POST /v1/scores` ·
`GET /v1/projects` · `POST /v1/verify`.

**CLI (run as module):** `python -m prism.cli {init|serve|up|dashboard|project|prompts|eval}`.

**SDK API:** `prism.init(...)` · `prism.trace(name, user_id=, session_id=, metadata=)`
· `prism.span(name, kind=)` · `prism.observe(name=, kind=)` ·
`prism.capture_llm(call, request=, model=, prompt_id=)` ·
`prism.llm.generate(message, system_prompt=, model=, prompt_id=, params=)` ·
`prism.shutdown()` · `prism.dropped()` ·
`prism.integrations.langchain.PrismCallbackHandler`.

**App env (via the obs shim):** `PRISM_ENABLED`, `PRISM_COLLECTOR_URL`,
`PRISM_INGEST_KEY`, `PRISM_ENV`, `PRISM_VERIFY`, `PRISM_TRACK_COST`.

**Guarantees:** never throws into your code · never blocks (enqueue + background
flush, drop-on-overflow) · tokens-not-dollars by default · audit hashes
(SHA-256 of input/output) stamped even when text capture is off.

**Gotchas:** set `PYTHONPATH` in every new terminal · use `python -m prism.cli`
(no `prism` command since we didn't install) · if the dashboard looks empty, widen
the time window to **all** and confirm the app and dashboard point at the same `--db`.
