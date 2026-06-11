"""Reference-based scoring (regression vs a golden output).

Complements the reference-FREE LLM-judge: when you have a known-good expected
output for a given input, ROUGE-L measures word-overlap drift cheaply (pure Python,
no model). References are keyed by the SHA-256 of the input prompt — record an
expected output for a known input, and any captured span with that input gets
scored. (Mirrors dev_check.py's baseline model.)

Also exposes content hashing for audit/reproducibility (prod_monitor.py idea).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

# Verdict thresholds (absolute ROUGE-L F1). Calibrate per task.
FAIL_FLOOR = 0.30
WARN_FLOOR = 0.45

_scorer = None


def _get_scorer():
    global _scorer
    if _scorer is None:
        from rouge_score import rouge_scorer
        _scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
    return _scorer


def sha256(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rouge_l(reference: str, candidate: str) -> dict:
    """Return {value, verdict, notes} for ROUGE-L F1 of candidate vs reference."""
    reference, candidate = (reference or "").strip(), (candidate or "").strip()
    if not reference or not candidate:
        return {"value": 0.0, "verdict": "FAIL", "notes": "empty reference or candidate"}
    f = _get_scorer().score(reference, candidate)["rougeL"].fmeasure
    value = round(float(f), 4)
    verdict = "FAIL" if value < FAIL_FLOOR else "WARN" if value < WARN_FLOOR else "PASS"
    notes = ""
    rw, cw = len(reference.split()), len(candidate.split())
    if rw and cw / rw < 0.5:
        notes = f"candidate much shorter ({cw} vs {rw} words) — may be truncated"
    elif rw and cw / rw > 2.0:
        notes = f"candidate much longer ({cw} vs {rw} words) — may be over-generating"
    return {"value": value, "verdict": verdict, "notes": notes}


def load_references(path: str) -> dict[str, str]:
    """Load a references file -> {input_sha256: reference_text}.

    File format: JSON list of {"input": "<prompt>", "reference": "<expected>"}.
    Inputs are hashed so matching is exact and the file stays human-readable.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    out: dict[str, str] = {}
    for item in json.loads(p.read_text()):
        inp, ref = item.get("input"), item.get("reference")
        if inp and ref:
            out[sha256(inp)] = ref
    return out


def score_span(span: dict, refs: dict[str, str]) -> list[dict]:
    """If the span's input has a recorded reference, return a rouge_l score."""
    if span.get("type") != "llm":
        return []
    ref = refs.get(sha256(span.get("user_message")))
    if not ref:
        return []
    r = rouge_l(ref, span.get("response_text") or "")
    return [{"span_id": span.get("span_id"), "trace_id": span.get("trace_id"),
             "name": "rouge_l", "value": r["value"], "label": r["verdict"],
             "source": "reference", "rationale": r["notes"]}]
