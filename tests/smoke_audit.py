"""Audit smoke: SDK stamps output/input hashes; /v1/verify proves match + detects
tampering. Fake gateway, in-process collector — no Ollama."""

import os
import tempfile
import threading
import time

import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

import prism
from prism.audit import sha256, verify
from prism.store import dao

gw = FastAPI()
_OUT = "The Q3 risk report identifies three risks: liquidity, credit, operational."


@gw.post("/api/llm/process")
def process(req: dict):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": _OUT}]},
                            "finishReason": "STOP", "safetyRatings": []}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 12, "totalTokenCount": 22},
            "modelVersion": "gemini-2.5-flash", "createTime": "x", "responseId": "r"}


def main():
    # pure-helper checks
    assert verify(sha256("abc"), "abc") and not verify(sha256("abc"), "xyz")

    db_path = os.path.join(tempfile.mkdtemp(), "audit.db")
    os.environ["PRISM_DB"] = db_path
    from prism.collector.app import create_app
    collector = create_app(db_path)

    threading.Thread(target=lambda: uvicorn.run(gw, host="127.0.0.1", port=8323, log_level="error"),
                     daemon=True).start()
    time.sleep(2.0)

    prism.init(app="audit-app", endpoint="http://127.0.0.1:8323/api/llm/process",
               collector_url="http://unused")  # we submit via TestClient below
    # capture a span through the SDK (force-full client)
    msg = "Summarise the Q3 risk report."
    prism.llm.generate(message=msg, model="gemini-2.5-flash")
    t = prism.config.get_transport()
    # grab the span the SDK queued, submit it via the collector TestClient
    span = t.q.get(timeout=2)
    prism.shutdown()

    with TestClient(collector) as client:
        client.post("/v1/ingest", json={"schema_version": 1, "spans": [span]})
        time.sleep(0.8)
        # the stored span has the hashes
        spans = dao.recent_spans(db_path, limit=5)
        llm = [s for s in spans if s["type"] == "llm"][0]
        print("output_hash:", (llm["output_hash"] or "")[:16], "input_hash:", (llm["input_hash"] or "")[:16])
        assert llm["output_hash"] == sha256(_OUT), "output hash mismatch"
        assert llm["input_hash"] == sha256(msg), "input hash mismatch"

        # /v1/verify: correct text matches, tampered text fails
        ok = client.post("/v1/verify", json={"span_id": llm["span_id"], "output": _OUT}).json()
        bad = client.post("/v1/verify", json={"span_id": llm["span_id"], "output": "tampered text"}).json()
        print("verify(correct).match =", ok["match"], "| verify(tampered).match =", bad["match"])
        assert ok["match"] is True and bad["match"] is False

    print("✅ AUDIT OK — full-text hashes stamped at capture; /v1/verify proves match + detects tamper")


if __name__ == "__main__":
    main()
