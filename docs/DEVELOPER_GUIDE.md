# Prism — Developer Implementation Guide

Hands-on: **run Prism locally** (collector + dashboard), then **instrument your app**
with the SDK functions. Copy-paste friendly. For the broader DevOps/User guide see
[GETTING_STARTED.md](GETTING_STARTED.md).

- [1. Run the services locally](#1-run-the-services-locally)
- [2. Install the SDK in your app](#2-install-the-sdk-in-your-app)
- [3. The functions you'll use](#3-the-functions-youll-use)
- [4. Minimal complete example](#4-minimal-complete-example-copy-paste)
- [5. The optional `obs.py` shim (recommended)](#5-the-optional-obspy-shim-recommended)
- [6. LangChain / LangGraph](#6-langchain--langgraph)
- [7. Verify it's working](#7-verify-its-working)
- [8. Quick reference](#8-quick-reference)

---

## 1. Run the services locally

Install the server pieces and the CLI:
```bash
git clone <this repo> prism && cd prism
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[collector,dashboard,cli,evals]"
```

### Option A — one command (easiest)
```bash
prism up --db ~/.prism/prism.db
#   collector  http://127.0.0.1:9100
#   dashboard  http://127.0.0.1:8052
#   (Ctrl-C stops both; add --eval for a continuous eval loop)
```

### Option B — separately (two terminals)
```bash
# terminal 1 — collector (the only writer; receives spans over HTTP)
prism serve --db ~/.prism/prism.db --port 9100

# terminal 2 — dashboard (read-only viewer)
prism dashboard --db ~/.prism/prism.db --port 8052
```

### Create a project (tenant) → get an ingest key
Your app authenticates to the collector with a per-project key:
```bash
prism project create "My App" --db ~/.prism/prism.db
#   project_id : prj_…
#   ingest_key : pk_…        <-- use this as PRISM_INGEST_KEY in your app
```

Sanity check: `curl http://127.0.0.1:9100/health` → `{"status":"ok",...}` and open
`http://127.0.0.1:8052`.

---

## 2. Install the SDK in your app

Your application only needs the SDK core (just `httpx`); add `langchain` if you use it.
```bash
pip install -e /path/to/prism                 # SDK core
pip install -e /path/to/prism[langchain]      # + LangChain/LangGraph handler
```

---

## 3. The functions you'll use

### 3.1 `prism.init(...)` — once, at startup
```python
import prism
prism.init(
    app="my-app",                                  # app_id on every span
    endpoint="http://localhost:8000/api/llm/process",  # YOUR LLM gateway
    collector_url="http://127.0.0.1:9100",          # the collector
    ingest_key="pk_…",                              # this project's key
    env="dev",
    capture_io=True,        # store prompt/response text (hashes computed regardless)
    track_cost=False,       # tokens only by default
    verify=True,            # TLS verify: True | False | "/path/to/cert.pem"
)
# ... your app ...
prism.shutdown()           # flush the background queue before exit
```
If `init` is never called, **every Prism call below is a silent no-op** — your app
runs unchanged.

### 3.2 `prism.trace(...)` — one trace per request
A trace groups everything one user interaction does. Use it as a **context manager**
or a **decorator**.
```python
# context manager
with prism.trace("handle_request", user_id="alice", session_id="sess-1"):
    do_work()

# decorator (sync or async)
@prism.trace("handle_request")
def handle(req): ...
```

### 3.3 `prism.span(...)` / `@prism.observe(...)` — mark a step
```python
with prism.span("retrieval", kind="retrieval") as s:
    docs = search(q)
    s.input(q); s.output(docs); s.attr(top_k=8)

@prism.observe(kind="tool")        # span around any function (sync/async)
def fetch_account(account_id): ...
```
`kind ∈ {llm, tool, retrieval, chain, agent, span}`.

### 3.4 The LLM call — `prism.llm.generate(...)` or `prism.capture_llm(...)`
This is the most valuable span (real tokens, cost, finish reason, audit hashes).

**If your endpoint is the `/api/llm/process` (Gemini) gateway contract** — use the
ready-made client (it forces `full_gemini_response="true"`, harvests real tokens, and
returns the shape you asked for):
```python
resp = prism.llm.generate(
    message=user_msg, system_prompt=sys, model="gemini-2.5-flash",
    params={"temperature": 0.2, "max_new_token": 1024},
    prompt_id="my-app/answer@v1",      # optional: link to a prompt version
)
```

**If your endpoint has a different shape** — wrap your own HTTP call. `capture_llm`
needs the *raw* response so it can parse tokens and hash the I/O:
```python
import httpx
def _call():
    r = httpx.post(GATEWAY, json=body, timeout=120)   # body has full_gemini_response="true"
    r.raise_for_status()
    return r                                            # return the raw Response

resp = prism.capture_llm(_call, request=body, model="gemini-2.5-flash",
                         prompt_id="my-app/answer@v1")
text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
```
> Why a wrapper and not a decorator here: the rich `llm` span (tokens/cost/hashes)
> needs the **unparsed gateway response**. A generic `@observe` only sees args/return
> and would produce a plain span without those metrics. Keep the LLM call as a
> `capture_llm` wrapper; use decorators for your *business* functions.

### 3.5 `prism.current_trace_id()` — deep-link a request to the dashboard
```python
with prism.trace("handle_request", user_id="alice"):
    result = run()
    tid = prism.current_trace_id()
# show the user: f"http://127.0.0.1:8052/?trace={tid}"   (opens that exact trace)
```

### 3.6 Cross-process tracing (frontend → backend)
Propagate a W3C `traceparent` so one trace spans services:
```python
# caller
headers = {}; prism.inject(headers); requests.post(url, headers=headers, json=…)

# callee
with prism.continue_trace(headers=request.headers, name="POST /chat",
                          user_id="alice"):
    ...
```

---

## 4. Minimal complete example (copy-paste)

A tiny app, fully instrumented, from scratch:
```python
import prism

prism.init(app="demo", endpoint="http://localhost:8000/api/llm/process",
           collector_url="http://127.0.0.1:9100", ingest_key="pk_…")

@prism.trace("answer_question")                 # one trace per call
def answer(question: str, user: str) -> str:
    resp = prism.llm.generate(message=question, model="gemini-2.5-flash",
                              prompt_id="demo/answer@v1")
    return resp                                  # llm span captured automatically

if __name__ == "__main__":
    print(answer("What is observability?", user="alice"))
    print("trace:", f"http://127.0.0.1:8052/?trace={prism.current_trace_id()}")
    prism.shutdown()
```
Run it (with the collector up) → the call appears as a trace in the dashboard within
~5s.

---

## 5. The optional `obs.py` shim (recommended)

So your app still runs when Prism **isn't installed** (and Prism turns on only via an
env flag), put a thin shim in your package and route everything through it. This is
the pattern `loan_agent` uses:

```python
# yourapp/obs.py
import contextlib, os
try:
    import prism
except Exception:                      # Prism not installed -> all no-ops
    prism = None
_ENABLED = False

def init_from_env() -> bool:
    global _ENABLED
    if prism is None or os.environ.get("PRISM_ENABLED","").lower() not in ("1","true","yes"):
        return False
    prism.init(
        app="yourapp",
        endpoint=os.environ["YOURAPP_GATEWAY_URL"],
        collector_url=os.environ.get("PRISM_COLLECTOR_URL", "http://127.0.0.1:9100"),
        ingest_key=os.environ.get("PRISM_INGEST_KEY"),
        env=os.environ.get("PRISM_ENV", "dev"),
        track_cost=os.environ.get("PRISM_TRACK_COST","").lower() in ("1","true","yes"),
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
def current_trace_id():
    return prism.current_trace_id() if _ENABLED else None
```

Then call `obs.init_from_env()` at startup, `obs.shutdown()` on exit, and use
`obs.trace / obs.span / obs.capture_llm / obs.callbacks` everywhere. Enable it at run
time with no code change:
```bash
PRISM_ENABLED=1 PRISM_COLLECTOR_URL=http://127.0.0.1:9100 PRISM_INGEST_KEY=pk_… python -m yourapp
```

---

## 6. LangChain / LangGraph

One line — pass the handler and every chain/tool/LLM node becomes a nested span:
```python
from prism.integrations.langchain import PrismCallbackHandler   # or obs.callbacks()
chain.invoke(inputs, config={"callbacks": [PrismCallbackHandler()]})
graph.invoke(state,  config={"callbacks": [PrismCallbackHandler()]})
```
Use this **instead of** decorating each node — the handler nests the tree and names
nodes for you.

### Versioned prompts (optional)
Store prompts as files (`<root>/<app>/<name>/vN.prompt`) and pass the ref so spans
link to the version:
```python
from prism.prompts import PromptRepo
p = PromptRepo("prompts").load("yourapp", "answer")   # latest; or load(..., version=2)
resp = prism.llm.generate(message=q, system_prompt=p.render(), prompt_id=p.ref)
```

---

## 7. Verify it's working

1. **Dashboard** → http://127.0.0.1:8052 → **Traces** tab: your call appears within ~5s
   (widen the time **window** to `all` if you don't see it).
2. Click the trace → span tree + **Prompts & responses** (each LLM span shows tokens
   and a 🔒 audit hash).
3. Programmatic checks:
   - `prism.dropped()` → spans dropped (queue overflow / collector down). Should be 0.
   - `curl -X POST http://127.0.0.1:9100/v1/verify -d '{"span_id":"…","output":"…"}'`
     → `{"match": true/false}` (audit/tamper check).
4. **Score quality** (optional): `prism eval --collector http://127.0.0.1:9100
   --judge-url <gateway>` → fills the **Quality** tab. Add `--watch` to run it
   continuously (incremental).

Nothing showing up? Check, in order: `init()` was called; `collector_url`/`ingest_key`
correct; collector `/health` is 200; `PRISM_REQUIRE_KEY` isn't rejecting your key
(`401`); TLS `verify` points at the right cert.

---

## 8. Quick reference

**Functions**
| Call | Use |
|---|---|
| `prism.init(app, endpoint, collector_url, ingest_key, …)` | once at startup |
| `prism.trace(name, user_id=, session_id=)` | one trace per request (cm/decorator) |
| `prism.span(name, kind=)` · `@prism.observe(kind=)` | a step / function span |
| `prism.llm.generate(message, model, prompt_id=)` | LLM call (gateway contract) |
| `prism.capture_llm(call, request=, model=, prompt_id=)` | wrap your own LLM HTTP call |
| `prism.current_trace_id()` | deep-link id for the dashboard |
| `prism.inject(headers)` / `prism.continue_trace(headers=)` | cross-process tracing |
| `prism.shutdown()` / `prism.dropped()` | flush on exit / self-check |
| `PrismCallbackHandler()` | LangChain/LangGraph auto-instrument |

**Local services**
| Command | Does |
|---|---|
| `prism up --db ~/.prism/prism.db` | collector + dashboard together |
| `prism serve --db … --port 9100` | collector only |
| `prism dashboard --db … --port 8052` | dashboard only |
| `prism project create "X"` | a tenant + its ingest key |
| `prism eval [--watch] [--judge-url …]` | score quality (one-shot / scheduled) |

**App env**
`PRISM_ENABLED=1` · `PRISM_COLLECTOR_URL` · `PRISM_INGEST_KEY` · `PRISM_ENV` ·
`PRISM_TRACK_COST` · `PRISM_VERIFY`.
