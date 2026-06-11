"""LLM-judge smoke: GatewayJudge against a fake gateway -> 3 quality scores;
runner combines heuristics + judge."""

import threading
import time

import uvicorn
from fastapi import FastAPI

from prism.evals.judge import GatewayJudge
from prism.evals.runner import score_recent  # noqa: F401 (import sanity)

gw = FastAPI()


@gw.post("/api/llm/process")
def process(req: dict):
    # The judge always asks for JSON ratings; return a fixed grade.
    grade = '{"relevance": 5, "coherence": 4, "safety": 5, "rationale": "on-topic, clear"}'
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": grade}]},
                            "finishReason": "STOP", "safetyRatings": []}],
            "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 20, "totalTokenCount": 50},
            "modelVersion": "judge", "createTime": "2026-06-11T00:00:00Z", "responseId": "j"}


def main():
    threading.Thread(target=lambda: uvicorn.run(gw, host="127.0.0.1", port=8311, log_level="error"),
                     daemon=True).start()
    time.sleep(2.0)

    judge = GatewayJudge("http://127.0.0.1:8311/api/llm/process", model="gemini-2.5-flash")
    span = {"type": "llm", "span_id": "s1", "trace_id": "t1",
            "user_message": "What is 2+2?", "response_text": "4"}
    scores = judge.score_span(span)
    names = {s["name"]: s for s in scores}
    print("judge scores:", {n: s["value"] for n, s in names.items()})

    assert names["judge_relevance"]["value"] == 5.0
    assert names["judge_coherence"]["value"] == 4.0
    assert names["judge_safety"]["value"] == 5.0
    assert all(s["source"] == "llm_judge" for s in scores)
    assert all(s["span_id"] == "s1" for s in scores)
    # non-llm span -> no judge scores; empty response -> none
    assert judge.score_span({"type": "chain"}) == []
    assert judge.score_span({"type": "llm", "response_text": ""}) == []

    print("✅ JUDGE OK — GatewayJudge produces relevance/coherence/safety scores")


if __name__ == "__main__":
    main()
