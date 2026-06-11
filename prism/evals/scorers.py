"""Heuristic scorers — fast, no LLM, deterministic.

Each scorer takes a span dict and returns a score dict (or None to skip). Score
shape matches the collector's /v1/scores contract:
    {span_id, trace_id, name, value, label, source, rationale}
Scorers only apply to llm spans (those with a response).
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

DEFAULT_LATENCY_SLO_MS = 8000
DEFAULT_TOKEN_BUDGET = 4000

_REFUSAL = re.compile(
    r"\b(i('|\s)?m sorry|i cannot|i can't|cannot help|unable to (help|assist|comply)|"
    r"as an ai|i am not able)\b", re.I)


def _base(span: dict, name: str, value, label: str, rationale: str = "") -> dict:
    return {"span_id": span.get("span_id"), "trace_id": span.get("trace_id"),
            "name": name, "value": float(value) if value is not None else None,
            "label": label, "source": "heuristic", "rationale": rationale}


def latency_slo(span: dict, slo_ms: float = DEFAULT_LATENCY_SLO_MS) -> Optional[dict]:
    dur = span.get("duration_ms")
    if dur is None:
        return None
    breach = dur > slo_ms
    return _base(span, "latency_slo", dur, "breach" if breach else "ok",
                 f"{dur:.0f}ms vs slo {slo_ms:.0f}ms")


def token_budget(span: dict, budget: int = DEFAULT_TOKEN_BUDGET) -> Optional[dict]:
    tot = span.get("total_tokens")
    if tot is None:
        return None
    breach = tot > budget
    return _base(span, "token_budget", tot, "breach" if breach else "ok",
                 f"{tot} tokens vs budget {budget}")


def empty_or_refusal(span: dict) -> Optional[dict]:
    text = (span.get("response_text") or "").strip()
    if not text:
        return _base(span, "answered", 0, "empty", "empty response")
    if _REFUSAL.search(text):
        return _base(span, "answered", 0, "refusal", "looks like a refusal")
    return _base(span, "answered", 1, "ok", "")


def json_valid(span: dict) -> Optional[dict]:
    text = (span.get("response_text") or "").strip()
    # Only judge spans whose output is meant to be JSON-ish.
    if not (text.startswith("{") or text.startswith("[")):
        return None
    try:
        json.loads(text)
        return _base(span, "json_valid", 1, "ok", "")
    except Exception:  # noqa: BLE001
        return _base(span, "json_valid", 0, "invalid", "response not parseable JSON")


def response_length(span: dict) -> Optional[dict]:
    text = span.get("response_text")
    if text is None:
        return None
    n = len(text)
    return _base(span, "response_chars", n, "ok", f"{n} chars")


HEURISTICS: list[Callable[[dict], Optional[dict]]] = [
    latency_slo, token_budget, empty_or_refusal, json_valid, response_length,
]


def score_span(span: dict, scorers: Optional[list] = None) -> list[dict]:
    """Run all heuristic scorers over one span; only llm spans are scored."""
    if span.get("type") != "llm":
        return []
    out = []
    for fn in (scorers or HEURISTICS):
        try:
            s = fn(span)
        except Exception:  # noqa: BLE001 — a bad scorer must not break the batch
            s = None
        if s is not None:
            out.append(s)
    return out
