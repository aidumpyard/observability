"""Dashboard smoke test — populate a temp store, then exercise the read layer +
figure builders + app construction (without launching the blocking server).
"""

import os
import tempfile
import time

from prism.store import Writer
from prism.dashboard import queries
from prism.dashboard.app import build_timeseries, build_model_bar, build_waterfall, create_app


def _span(writer, **kw):
    base = dict(schema_version=1, env="test", app_type="langgraph", status="ok",
                started_at="2026-06-11T10:00:00.000Z", ended_at="2026-06-11T10:00:01.000Z",
                created_at="2026-06-11T10:00:00.000Z")
    base.update(kw)
    writer.submit_spans([base])


def main():
    db_path = os.path.join(tempfile.mkdtemp(), "dash.db")
    w = Writer(db_path).start()

    # one loan trace: root chain -> graph -> 1 agent(chain) -> llm ; plus extract->llm
    tid = "t" * 32
    _span(w, span_id="s_root", trace_id=tid, parent_span_id=None, type="chain",
          name="loan_process", app_id="loan_agent")
    _span(w, span_id="s_graph", trace_id=tid, parent_span_id="s_root", type="chain",
          name="LangGraph", app_id="loan_agent")
    _span(w, span_id="s_agent", trace_id=tid, parent_span_id="s_graph", type="chain",
          name="completeness", app_id="loan_agent")
    _span(w, span_id="s_llm1", trace_id=tid, parent_span_id="s_agent", type="llm",
          name="gemini-2.5-flash", model="gemini-2.5-flash", app_id="loan_agent",
          prompt_tokens=60, completion_tokens=30, total_tokens=90, tokens_source="model",
          cost_usd=0.000027, duration_ms=640,
          started_at="2026-06-11T10:00:00.100Z", ended_at="2026-06-11T10:00:00.740Z")
    _span(w, span_id="s_extract", trace_id=tid, parent_span_id="s_root", type="chain",
          name="extract", app_id="loan_agent")
    _span(w, span_id="s_llm2", trace_id=tid, parent_span_id="s_extract", type="llm",
          name="gemini-2.5-flash", model="gemini-2.5-flash", app_id="loan_agent",
          prompt_tokens=120, completion_tokens=40, total_tokens=160, tokens_source="model",
          cost_usd=0.000042, duration_ms=820,
          started_at="2026-06-11T10:00:00.000Z", ended_at="2026-06-11T10:00:00.820Z")
    time.sleep(1.0)
    w.shutdown()

    # --- queries ---
    o = queries.overview(db_path, hours=0)
    print("overview:", o)
    assert o["calls"] == 2, o["calls"]
    assert o["tokens"] == 250, o["tokens"]
    assert round(o["cost"], 6) == 0.000069, o["cost"]
    assert o["traces"] == 1

    apps = queries.list_apps(db_path); print("apps:", apps); assert apps == ["loan_agent"]
    ba = queries.by_app(db_path, hours=0); assert ba[0]["calls"] == 2
    bm = queries.by_model(db_path, hours=0); assert bm[0]["model"] == "gemini-2.5-flash"
    ts = queries.timeseries(db_path, hours=0); assert ts and ts[0]["calls"] == 2

    traces = queries.recent_traces(db_path, hours=0)
    print("trace row:", traces[0])
    assert traces[0]["spans"] == 6 and traces[0]["tokens"] == 250
    assert traces[0]["status"] == "ok"

    spans = queries.trace_spans(db_path, tid); assert len(spans) == 6

    # --- figure builders ---
    assert build_timeseries(ts).data
    assert build_model_bar(bm).data
    wf = build_waterfall(spans); assert wf.data, "waterfall empty"
    print("waterfall bars:", sum(len(t.x) if hasattr(t, 'x') and t.x is not None else 0 for t in wf.data))

    # --- app constructs (layout + callbacks registered) ---
    app = create_app(db_path)
    assert app.layout is not None
    print("\n✅ DASHBOARD OK — queries, figures, and Dash app all build against real data")


if __name__ == "__main__":
    main()
