"""Fake Gemini-style gateway for Prism demos.

Stands in for a real ``/api/llm/process`` LLM gateway so you can populate the
collector with realistic ``loan_agent`` traffic without any API keys. It returns
a full Gemini envelope (with ``usageMetadata``) so Prism harvests real token
counts.

Run::

    python scripts/demo/fake_gw.py        # listens on 127.0.0.1:8400

Override the port with the ``PRISM_FAKE_GW_PORT`` env var.
"""
import json
import os
import re

import uvicorn
from fastapi import FastAPI

gw = FastAPI()
_AMOUNT = re.compile(r"(?:USD|\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|bn)?\b", re.I)


def _envelope(text: str) -> dict:
    return {
        "candidates": [{
            "content": {"role": "model", "parts": [{"text": text}]},
            "finishReason": "STOP", "safetyRatings": [],
        }],
        "usageMetadata": {"promptTokenCount": 60, "candidatesTokenCount": 30,
                          "totalTokenCount": 90},
        "modelVersion": "gemini-2.5-flash", "createTime": "x", "responseId": "r",
    }


def _amount(text: str) -> float:
    for line in text.splitlines():
        if "value" in line.lower():
            m = _AMOUNT.search(line)
            if m:
                n = float(m.group(1).replace(",", ""))
                scale = (m.group(2) or "").lower()
                return n * (1e6 if scale == "million" else 1e9 if scale == "bn" else 1)
    return 1_500_000


@gw.post("/api/llm/process")
def process(req: dict):
    system_prompt = (req.get("system_prompt") or "").lower()
    message = req.get("message", "")
    if "extraction engine" in system_prompt:
        client = ("Orion Energy Holdings Ltd" if "orion" in message.lower()
                  else "Acme Manufacturing Pvt Ltd")
        return _envelope(json.dumps({
            "value": _amount(message), "currency": "USD", "tenure": "48 months",
            "interest_rate": "8%", "date": "2026-03-14",
            "product_name": "Term Loan", "client_name": client,
        }))
    risky = "orion" in message.lower() or "cross-border" in message.lower()
    verdict = ('{"verdict":"CONCERN","risk":55,"notes":"large cross-border","flags":["cross-border"]}'
               if risky else
               '{"verdict":"PASS","risk":18,"notes":"clean","flags":[]}')
    return _envelope(verdict)


if __name__ == "__main__":
    port = int(os.environ.get("PRISM_FAKE_GW_PORT", "8400"))
    uvicorn.run(gw, host="127.0.0.1", port=port, log_level="error")
