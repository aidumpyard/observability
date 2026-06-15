"""Scheduled-eval mechanics: incremental judging (skip already-judged) + max_judge
budget. Uses a fake judge gateway; scores computed via score_recent (no collector)."""

import os
import tempfile
import threading
import time

import uvicorn
from fastapi import FastAPI

from prism.evals.judge import GatewayJudge
from prism.evals.runner import score_recent
from prism.store import Writer, init_db

gw = FastAPI()


@gw.post("/api/llm/process")
def process(req: dict):
    g = '{"relevance":5,"coherence":4,"safety":5,"rationale":"ok"}'
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": g}]},
                            "finishReason": "STOP", "safetyRatings": []}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 5, "totalTokenCount": 10},
            "modelVersion": "judge", "createTime": "x", "responseId": "j"}


def _judge_ids(scores):
    return {s["span_id"] for s in scores if s["source"] == "llm_judge"}


def main():
    db = os.path.join(tempfile.mkdtemp(), "loop.db")
    init_db(db)
    w = Writer(db).start()
    for i in range(5):
        w.submit_spans([{"span_id": f"s{i}", "trace_id": f"t{i}", "type": "llm",
                         "name": "x", "user_message": f"q{i}", "response_text": f"a{i}",
                         "schema_version": 1, "started_at": "2026-06-12T10:00:00Z",
                         "created_at": "2026-06-12T10:00:00Z"}])
    time.sleep(0.8)

    threading.Thread(target=lambda: uvicorn.run(gw, host="127.0.0.1", port=8333, log_level="error"),
                     daemon=True).start()
    time.sleep(2.0)
    judge = GatewayJudge("http://127.0.0.1:8333/api/llm/process")

    # cycle 1: judge all 5
    s1 = score_recent(db, judge=judge)
    assert len(_judge_ids(s1)) == 5, _judge_ids(s1)

    # budget: only judge 2 this run
    s2 = score_recent(db, judge=judge, max_judge=2)
    assert len(_judge_ids(s2)) == 2, _judge_ids(s2)

    # persist cycle-1 judge scores, then incremental run judges 0 new
    w.submit_scores(s1); time.sleep(0.8); w.shutdown()
    s3 = score_recent(db, judge=judge, skip_judged=True)
    assert len(_judge_ids(s3)) == 0, f"incremental should skip judged: {_judge_ids(s3)}"
    # heuristics still ran for all spans
    assert any(s["source"] == "heuristic" for s in s3)

    print("✅ EVAL-LOOP OK — incremental (skip_judged) judges only new spans; max_judge caps cost")


if __name__ == "__main__":
    main()
