# Prism SDK — Instrumentation Surface

How agent products talk to Prism. One mental model — **Trace → Spans** — exposed
through layered APIs so any call style (raw HTTP, LangChain, LangGraph, plain
functions) produces the *same* normalized span record. Two non-negotiables:

> **N1 — Never throws.** Every Prism entry point is wrapped so a capture failure is
> logged and dropped; the product code path continues as if Prism weren't there.
>
> **N2 — Never blocks.** Capture does the minimum on the calling thread (stamp a few
> fields, enqueue) and offloads serialization + persistence to a background worker.
> A bounded queue drops-on-overflow rather than back-pressure the product.

## Layer 0 — init (once per process)

```python
import prism
prism.init(
    app="claims-agent",
    endpoint="http://localhost:8000/api/llm/process",  # gateway; real server in prod
    api_key="…",
    sample_rate=1.0,        # head sampling by trace; <1.0 makes unsampled spans no-ops
    capture_io=True,        # capture prompt/response text (subject to redaction)
    redact=prism.pii_redactor,
    max_text_chars=8000,    # truncate large payloads
)
```

If `init` is never called, or the backend is unreachable, **every API becomes a
silent no-op** — products still run.

## Layer 1 — tracing primitives (framework-agnostic)

The spine. A **trace** is one product interaction; **spans** nest beneath it.
Context flows via `contextvars` (async- and thread-safe), so nesting is automatic —
no manual parent passing.

```python
# decorator — works on sync OR async functions
@prism.trace(name="checkout")
def handle_checkout(cart, user): ...

@prism.observe(kind="tool")           # a span around any function
async def fetch_account(account_id): ...

# context manager — for inline blocks
with prism.span("retrieval", kind="retrieval") as s:
    docs = vector_search(q)
    s.input(q); s.output(docs); s.attr(top_k=8)
```

`kind ∈ {llm, tool, retrieval, chain, agent, span}`. Spans auto-record
duration, status, and exceptions (re-raised to the product **only** if they
originate in the product code, never if they originate in Prism).

## Layer 2 — LLM calls (three ingestion styles, one record)

**(a) Prism client — recommended.** Wraps the gateway and applies the force-full
trick (§ARCHITECTURE.2): always sends `full_gemini_response="true"`, harvests real
tokens / `modelVersion` / `finishReason`, returns the caller's *original* shape.

```python
resp = prism.llm.generate(
    message=user_msg, system_prompt=sys, model="gemini-2.5-flash",
    params={"temperature": 0.7, "max_new_token": 1024},
    full_gemini_response="false",   # what the CALLER wants back; Prism still captures full
)
```

**(b) Wrap an existing raw call** — for agents already doing `httpx`/`requests`:

```python
# explicit wrap
resp = prism.capture_llm(lambda: httpx.post(url, json=body), request=body)

# OR zero-code auto-instrument — patches httpx/requests, fires ONLY for the
# configured gateway URL (URL-scoped so unrelated HTTP isn't touched)
prism.instrument_http()      # opt-in, called once after init
```

**(c) Streaming** is supported: the client/handler accumulates chunks, records
first-token latency + total, and yields to the product unchanged.

## Layer 3 — LangChain & LangGraph (auto-instrumentation)

A single callback handler covers both — LangChain and LangGraph share the callback
system, and `parent_run_id` gives correct nesting for chains, tools, agents, and
graph nodes for free.

```python
from prism.integrations.langchain import PrismCallbackHandler
cb = PrismCallbackHandler()        # reads current Prism trace from context

# LangChain
chain.invoke(input, config={"callbacks": [cb]})

# LangGraph — same handler; every node / tool / LLM call becomes a nested span
graph.invoke(state, config={"callbacks": [cb]})
```

Hooks mapped → spans: `on_chain_start/end` → chain span, `on_tool_start/end` →
tool span, `on_llm_start` / `on_chat_model_start` / `on_llm_end` → llm span (with
token usage from the response), `on_*_error` → error status. No product code inside
the graph changes; you just pass the handler in `config`.

## Layer 4 — end-to-end / distributed tracing (button → backend → gateway)

Uses **W3C `traceparent`** so it's standard and cross-language.

```python
# Inbound: continue a trace started upstream (frontend or another service)
from prism.integrations.fastapi import PrismASGIMiddleware
app.add_middleware(PrismASGIMiddleware)     # opens a trace per request,
                                            # reads incoming traceparent if present

# Manual continuation in any framework
with prism.continue_trace(headers=request.headers, name="POST /chat"):
    ...

# Outbound: propagate to a downstream service
headers = {}; prism.inject(headers); downstream.post(url, headers=headers, json=…)
```

**Frontend button → backend:** the browser generates a `traceparent` on click (tiny
snippet provided) and sends it as a request header; `PrismASGIMiddleware` continues
that exact trace. Result: one trace spans `button click → API → agent graph → every
LLM call → response`, viewable as a waterfall in the dashboard.

```
[trace] checkout (button click)                              1840ms
 ├─ span  POST /chat            (backend entry)              1835ms
 │   ├─ chain  agent_executor                                1700ms
 │   │   ├─ retrieval  vector_search                          120ms
 │   │   ├─ llm  gemini-2.5-flash  (plan)   312 tok  $0.0004   640ms
 │   │   ├─ tool  fetch_account                                90ms
 │   │   └─ llm  gemini-2.5-flash  (answer) 540 tok  $0.0009   810ms
```

## Cross-cutting guarantees (how N1 & N2 hold)

| Concern | Mechanism |
|---|---|
| No exceptions leak | Every public fn wrapped in `_safe()`; capture errors logged at DEBUG, dropped |
| No latency added | Hot path = stamp + enqueue; bounded `queue.Queue` → background worker batches to SQLite |
| Overflow | Drop-on-full (configurable), never blocks the producer |
| Async + threads | `contextvars` carry the active trace/span across `await` and executors |
| Sampling | Head sampling per trace; unsampled → span objects are no-ops (no I/O, no alloc of payloads) |
| Privacy | `capture_io` + `redact` hook + `max_text_chars`; `data_classification`-aware |
| Framework absent | Integrations import lazily; missing LangChain/httpx never breaks core |
| Backend down | Writes fail silent; product unaffected; queue drains when it recovers |

## Adoption ladder (lowest effort → richest signal)

1. `prism.init()` + `prism.instrument_http()` → every gateway call captured, zero code edits.
2. Add `PrismASGIMiddleware` → per-request traces + inbound propagation.
3. Add `PrismCallbackHandler` to LangChain/LangGraph configs → full node/tool/llm trees.
4. Add `@prism.trace` / `@prism.observe` on business functions → product-meaningful spans.
5. Add the frontend `traceparent` snippet → true button-to-end traces.
