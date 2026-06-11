# Prism — LLM Observability for the `/api/llm/process` Gateway

> Working name: **Prism** (light → spectrum → visibility). A 100% open-source,
> pip-only, single-process observability platform for products built on the
> company's Gemini gateway (simulated locally by ProjectLLMSimulator).

## 1. Design principles

1. **Zero infra.** No Docker, no servers to run besides plain `uvicorn`/`dash`
   processes. Storage is a single SQLite file. Everything is `pip install`.
2. **Never tax the product path.** Capture is fire-and-forget and async. If Prism
   is down or slow, the LLM request is unaffected. Observability must not add
   latency or a failure mode.
3. **The gateway is an opaque remote HTTP endpoint.** Prism connects to
   `…/api/llm/process` over HTTP — the real server in production, the simulator in
   test — and knows nothing about how it generates text. The model runtime behind
   it (Ollama/Qwen in the simulator) is **never** part of the product and is
   **never** counted; model identity is only ever what the gateway *reports*
   (`model` / `modelVersion`). Base URL + key are config. Capture is therefore
   **client-side** (SDK first; optional thin proxy) — see §3.
4. **Standards-aligned.** Attribute names follow OpenTelemetry GenAI semantic
   conventions (`gen_ai.*`) so data is portable to a "real" backend later without
   reinstrumenting.
5. **Truth over theater.** The gateway's `safetyRatings`/`avgLogprobs` are
   synthetic — Prism ignores them and computes *real* quality via a pluggable
   remote LLM judge (§6).

## 2. The signal that drives everything: `full_gemini_response`

The gateway changes its **response shape** based on this flag:

| | absent / `"false"` | `"true"` |
|---|---|---|
| Body | bare JSON string (text only) | full Gemini envelope |
| token usage, finishReason, modelVersion, responseId | ❌ absent | ✅ present |

**Consequence:** Prism does not own the production gateway, so it cannot read
server-side usage. Instead the **SDK transparently sets `full_gemini_response="true"`
on the outbound call**, reads the real token usage / `modelVersion` / `finishReason`
from the envelope, then returns to the caller whatever shape they *originally* asked
for (bare string or full envelope). This recovers full fidelity with **zero gateway
access** and works identically against the real server and the simulator. Only if
you happen to run the gateway yourself (the simulator in test) can optional
middleware capture the same data server-side as a cross-check.

## 3. Architecture (client-side capture)

```
                        PRODUCT / APPLICATION
                               │  calls Prism SDK instead of raw HTTP
              ┌────────────────┴───────────────────────────┐
              │  Prism SDK (pip)  ◄── PRIMARY CAPTURE        │  opens product-level
              │  @observe / trace() / generate()            │  TRACE; each gateway
              │  - sets full_gemini_response="true" outbound │  call = a SPAN with
              │  - reads real tokens / modelVersion / finish │  app_id, user_id,
              │  - returns caller's ORIGINAL requested shape │  session, business ctx
              └────────────────┬───────────────────────────┘
                               │ HTTPS  (base_url = config: real server | simulator)
                               ▼
        ┌──────────────────────────────────────────────┐
        │   REMOTE GATEWAY  /api/llm/process  (opaque)   │  Prism owns none of this;
        │   real server in prod · simulator in test      │  model runtime (Ollama/
        │   [optional middleware ONLY if you run it]      │  Qwen) is invisible & uncounted
        └───────────────────────┬──────────────────────┘
              span emitted async │ bounded queue → batched POST /v1/ingest (see §3.5)
                                ▼
        ┌──────────────────────────────────────────────┐
        │   COLLECTOR → STORE   SQLite (WAL), zero infra │  traces, spans, scores,
        └───────┬───────────────────────────┬──────────┘  prompts, apps, cost
                │                            │
        ┌───────▼──────────────────┐ ┌───────▼──────────────┐
        │ EVAL ENGINE (offline)    │ │ DASHBOARD (Dash)     │
        │ heuristics + pluggable   │ │ RED + cost + traces +│
        │ HTTP LLM-judge (tagged   │ │ evals + prompt repo  │
        │ internal=eval)           │ │ + live tail          │
        └──────────────────────────┘ └──────────────────────┘
```

The SDK is the single source of capture: it owns the `trace_id`, records the span
with **real** token/cost/latency (thanks to the forced `full_gemini_response`), and
hands the product back exactly the response shape it asked for. A thin reverse-proxy
variant (same logic, no code change) covers non-Python clients. Optional server
middleware exists **only** for gateways you run yourself (the simulator) as a
cross-check — it is never assumed in production.

## 3.5 Deployment & data plane (v1 decisions)

Products run on **different machines/hosts**, so the **collector is the fan-in
point** (not optional). Confirmed v1 scope:

- **Topology:** distributed producers → HTTPS → one central collector → central
  SQLite → dashboard. No shared filesystem assumed.
- **Publish surface:** **internal Dash (Plotly) dashboard only.** Query API, alerts, and
  exports are deferred — but the collector keeps those seams so they're additive.
- **Scale:** **< 100k calls/day.** SQLite (WAL) + batched single-writer inserts is
  comfortably within budget; revisit DuckDB/Postgres only past ~1M/day.

```
 Product A/B/C/D (any machine)
   SDK: bounded queue → batched POST /v1/ingest  (X-Prism-Key per app,
        retry+backoff, drop-on-overflow — never blocks the product)
        │  HTTPS
        ▼
 PRISM COLLECTOR  (FastAPI, `prism serve`) — ONE pip process, no docker
   • auth X-Prism-Key → app_id      • validate + normalize
   • SINGLE writer → batched txns   (no write contention)
        │
        ▼
 CENTRAL STORE  SQLite (WAL)  — one file, many concurrent readers
        │                         ┌──────────────┐
        ├───────────────────────► │ EVAL ENGINE  │ (offline; reads spans → writes
        │                         │              │  scores back via POST /v1/scores,
        │                         └──────────────┘  NOT a direct DB writer)
        └───────────────────────► │ DASHBOARD    │ (Dash/Plotly — the only egress in v1)
                                  └──────────────┘
```

**Multi-tool identity:** every event carries `app_id` (+ optional `env`,
`app_type`), authenticated by a per-app ingest key. All tool types (LangGraph
agent, raw-httpx chatbot, batch job) emit the *same* normalized span schema; the
collector is tool-agnostic and the dashboard groups by app. Cross-product flows
stitch by `trace_id` (W3C `traceparent`).

**Durability note:** default SDK buffer is in-memory (drop-on-overflow per N2). An
optional on-disk spool (small local SQLite) can be enabled per product if a
restart/collector-outage must not lose spans — at the cost of a little local I/O.

### Resolved operational decisions

- **One writer, by construction (B1).** Only the collector opens SQLite for
  writing, runs with **`workers=1`**, and funnels *all* writes (spans **and**
  scores) through **one internal writer thread / one connection** in batched
  transactions. The eval engine never writes directly — it `POST`s to
  `/v1/scores`. Plus `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`.
  Readers (dashboard, eval reads) never block the writer.
- **Time (B5).** Store everything in **UTC** (kills timezone ambiguity). Each span
  carries a **locally-measured `duration_ms`** (monotonic clock) — never derive
  durations by subtracting timestamps across hosts. The collector stamps
  `received_at` and computes a per-producer **clock offset** to shift spans onto a
  common timeline for the waterfall; intra-trace ordering uses `parent_span_id`.
- **Transport (B3).** Collector serves **HTTPS via a self-signed cert** generated
  in a non-admin home dir (`openssl req -x509 …`; `uvicorn --ssl-keyfile/-certfile`);
  the SDK trusts it with `verify=<cert>`. Reusing an existing server cert works
  *only* if you hold its private key **and** its SAN covers the collector host.
- **Schema versioning (C3).** Every ingest payload carries `schema_version`; the
  collector keeps a backward-compat normalization layer for mixed SDK versions.
- **Eval load (B4) — deferred.** The judge stays a plain HTTP call for now; eval
  sampling / budgeting is a later concern once volume warrants it.
- **Prompt repo (C1).** App-scoped — keyed by `(app_id, name, version)` with a
  `created_by` author field. Not per-user.

## 4. Data model (SQLite)

```
apps        (app_id PK, name, owner, created_at)
prompts     (prompt_id PK, app_id FK, name, version, template, variables_json,
             tags, created_by, created_at)              -- the prompt repo
traces      (trace_id PK, app_id, user_id, session_id, name, status,
             started_at, ended_at, duration_ms, metadata_json)
spans       (span_id PK, trace_id FK, parent_span_id,
             type[llm|tool|retrieval|chain|agent|span],
             name, model, prompt_id FK,
             params_json{temperature,top_k,top_p,max_new_token},
             system_prompt, user_message, response_text,
             prompt_tokens, completion_tokens, total_tokens, thoughts_tokens,
             tokens_source[model|estimated],            -- honesty flag
             finish_reason, full_gemini_response,
             cost_usd, duration_ms, status, error,      -- duration measured locally
             data_classification, response_id,
             app_id, env, app_type, schema_version,     -- producer identity + wire ver
             started_at, created_at,                    -- UTC, producer clock
             received_at)                               -- UTC, collector clock (skew)
scores      (score_id PK, span_id FK|trace_id FK, name, value REAL, label,
             source[heuristic|llm_judge|human], rationale, created_at)
costs       (model PK, input_per_1k, output_per_1k, currency)  -- pricing table
```

Indices on `trace_id`, `app_id`, `created_at`, `model` for the dashboard queries.
`tokens_source` is deliberate: never let an estimate masquerade as a measurement.

## 5. Components & the open-source, pip-only stack

| Component | Implementation | Packages (all OSS) |
|---|---|---|
| SDK (primary capture) | `@observe` / `trace()` / `generate()`; forces `full_gemini_response="true"` outbound, returns caller's original shape; opens traces, propagates context | stdlib, `httpx` |
| Server middleware (optional, self-run gateways only) | Pure-ASGI middleware for the simulator in test; never assumed in prod | `starlette` |
| Ingest/transport | Async in-proc queue → batched writer; optional `POST /v1` collector | `fastapi`, `uvicorn` |
| Store | SQLite WAL, thin DAO | stdlib `sqlite3` |
| Eval engine | Heuristics + **stateless HTTP LLM-judge** (pluggable: the gateway itself, or any Gemini/OpenAI-compatible API) | `httpx` |
| Dashboard | Multi-page analytics UI (callback graph, drill-down, live tail) | `dash`, `plotly`, `pandas` |
| CLI | `prism init|dashboard|eval run|serve` | `typer` |
| Conventions | `gen_ai.*` attribute mapping | optional `opentelemetry-sdk` |

No Docker, no external DB, no SaaS. One SQLite file + the `pip`-installed Prism
processes you run yourself: the **collector** (`prism serve`, the only DB writer),
the **dashboard** (Dash/Plotly), and the **eval engine** (batch job). The gateway is
external and unmodified.

## 6. Evaluation (this is where "state of the art" lives)

**Heuristic scorers** (no LLM, instant): latency-SLO breach, token-budget breach,
empty/refusal detection, response length, JSON-validity, PII/regex on classified data.

**LLM-as-judge** — relevance, coherence, helpfulness, faithfulness/groundedness
(when retrieval context exists), and **real toxicity/safety** (replacing the
gateway's fake `safetyRatings`). The judge is a **stateless HTTP client to a remote
LLM API** — there is no local model in production. It is **pluggable** behind a
`Judge` interface, with backends for the same `/api/llm/process` gateway contract
and any Gemini/OpenAI-compatible endpoint (Ollama is just one dev-only backend).
Config = base URL, model, API key, `full_gemini_response="true"` for structured
scores + token counts. The judge runs **offline** against stored spans, so it never
touches the product latency path — and because judge calls hit an observed endpoint,
they are tagged `internal=eval` so they don't pollute product metrics.

Scores attach per-span and aggregate per app / per user / per prompt-version →
enables prompt A/B testing and quality-regression alerts.

## 7. Prompt repo (per app + per user)

Versioned prompt templates keyed by `(app_id, name, version)`. Each `span` links to
the `prompt_id` that produced it. The dashboard shows version diffs and overlays
cost + latency + eval scores per version, so you can see whether prompt v3 actually
beat v2. Users register/fetch prompts via the SDK (`prism.prompts.get("app","name")`).

## 8. Cross-cutting

- **Cost**: `costs` table maps model → $/1k tokens; cost computed at write time.
- **Privacy**: `data_classification`-aware redaction + configurable retention;
  prompt/response capture can be hashed or truncated for non-Public data.
- **Sampling**: configurable rate (100% at low volume; head/tail sampling at scale).
- **Resilience**: bounded queue, drop-on-overflow, write failures logged not raised.

## 9. Build phases

- **Phase 0 — skeleton**: package layout, SQLite schema + DAO, `prism init`.
- **Phase 1 — capture spine**: collector (`/v1/ingest`, single in-proc writer
  thread, WAL, HTTPS) + SQLite store + minimal SDK (force-full `prism.llm` client +
  bounded queue → batched ingest with `schema_version`).
  *Milestone: every gateway call lands as a span with real token + latency + cost.*
- **Phase 2 — dashboard**: Dash (Plotly) Overview (RED + cost) + Traces explorer + trace
  waterfall (collector skew-correction) + live tail.
- **Phase 3 — evals**: heuristic scorers + pluggable remote HTTP LLM-judge (scores
  written via `POST /v1/scores`, never a direct DB write) + quality trends; retire
  the fake safety ratings.
- **Phase 4 — prompt repo**: versioning, diff, per-version quality/cost overlay.
- **Phase 5 — polish**: sampling, retention/redaction, OTel `gen_ai.*` export, alerts.
