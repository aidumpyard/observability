"""End-to-end spine smoke test — no real gateway, no Ollama needed.

1. Start a fake Gemini gateway (returns a full envelope) in-process.
2. Start the Prism collector against a temp SQLite db.
3. Use the SDK: open a trace, call prism.llm.generate (force-full), add a child span.
4. Assert the spans landed in SQLite with real tokens + computed cost + trace stitching.
"""

import os
import tempfile
import threading
import time

import uvicorn
from fastapi import FastAPI

import prism
from prism.store import dao

# --- fake gateway -----------------------------------------------------------
gw = FastAPI()


@gw.post("/api/llm/process")
def process(req: dict):
    # Mimic the simulator's full envelope; echo full_gemini_response handling.
    return {
        "candidates": [{
            "content": {"role": "model", "parts": [{"text": "Hello from fake gateway"}]},
            "finishReason": "STOP",
            "safetyRatings": [],
            "avgLogprobs": -0.3,
        }],
        "usageMetadata": {
            "promptTokenCount": 12, "candidatesTokenCount": 8, "totalTokenCount": 20,
            "promptTokensDetails": [], "candidatesTokensDetails": [], "thoughtsTokenCount": 0,
        },
        "modelVersion": req.get("model", "gemini-2.5-flash"),
        "createTime": "2026-06-11T00:00:00Z",
        "responseId": "fake123",
    }


def _serve(app, port):
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    db_path = os.path.join(tempfile.mkdtemp(), "prism_test.db")
    os.environ["PRISM_DB"] = db_path

    # collector must be created AFTER PRISM_DB is set
    from prism.collector.app import create_app
    collector = create_app(db_path)

    threading.Thread(target=_serve, args=(gw, 8123), daemon=True).start()
    threading.Thread(target=_serve, args=(collector, 9123), daemon=True).start()
    time.sleep(2.5)  # let both boot

    prism.init(
        app="smoke-app",
        endpoint="http://127.0.0.1:8123/api/llm/process",
        collector_url="http://127.0.0.1:9123",
        env="test", app_type="smoke",
        track_cost=True,   # this test specifically exercises the cost path
    )

    with prism.trace("smoke-flow", user_id="u-1"):
        # caller asks for plain text; Prism still captures full
        out = prism.llm.generate(message="hi there", model="gemini-2.5-flash",
                                 full_gemini_response="false")
        assert isinstance(out, str), f"expected text, got {type(out)}"
        with prism.span("post-process", kind="tool") as s:
            s.input(out).output(out.upper()).attr(step="upper")

    prism.shutdown()       # flush SDK transport
    time.sleep(1.5)        # let collector's writer commit

    spans = dao.recent_spans(db_path, limit=10)
    print(f"\nspans persisted: {len(spans)}")
    llm_spans = [s for s in spans if s["type"] == "llm"]
    assert llm_spans, "no llm span persisted"
    sp = llm_spans[0]
    print("llm span:", {k: sp[k] for k in
          ("type", "model", "prompt_tokens", "completion_tokens", "total_tokens",
           "tokens_source", "cost_usd", "finish_reason", "duration_ms")})

    assert sp["total_tokens"] == 20, sp["total_tokens"]
    assert sp["tokens_source"] == "model"
    assert sp["cost_usd"] and sp["cost_usd"] > 0, "cost not computed"
    assert sp["finish_reason"] == "STOP"

    tool_spans = [s for s in spans if s["type"] == "tool"]
    assert tool_spans, "no tool span"
    # trace stitching: both spans share one trace
    trace_ids = {s["trace_id"] for s in spans}
    assert len(trace_ids) == 1, f"spans not stitched: {trace_ids}"
    tid = trace_ids.pop()
    assert tool_spans[0]["parent_span_id"] == llm_spans[0]["span_id"] or \
           tool_spans[0]["parent_span_id"] is not None

    summ = dao.summary(db_path)
    print("summary:", summ)
    assert summ["calls"] == 1

    print(f"\ntrace {tid}: {len(dao.trace_spans(db_path, tid))} spans")
    print("dropped:", prism.dropped())
    print("\n✅ SPINE OK — SDK → collector → SQLite with real tokens, cost, and trace stitching")


if __name__ == "__main__":
    main()
