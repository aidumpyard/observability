"""Eval runner — read spans, score them, POST scores to the collector.

Offline batch job: never a direct DB writer. Reads spans read-only, runs scorers,
and submits results via the collector's /v1/scores endpoint so the single writer
persists them. Intended to be run periodically (cron) or on demand.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..store import dao
from ..version import SCHEMA_VERSION
from .scorers import score_span

log = logging.getLogger("prism.evals")


def score_recent(db_path: str, limit: int = 500) -> list[dict]:
    """Score the most recent llm spans; returns the list of score dicts."""
    spans = dao.recent_spans(db_path, limit=limit)
    scores: list[dict] = []
    for sp in spans:
        scores.extend(score_span(sp))
    return scores


def submit(collector_url: str, scores: list[dict], *, ingest_key: Optional[str] = None,
           verify=True, timeout: float = 10.0) -> int:
    """POST scores to the collector. Returns count accepted (best effort)."""
    if not scores:
        return 0
    headers = {"X-Prism-Key": ingest_key} if ingest_key else {}
    url = collector_url.rstrip("/") + "/v1/scores"
    payload = {"schema_version": SCHEMA_VERSION, "scores": scores}
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout, verify=verify)
        resp.raise_for_status()
        return int(resp.json().get("accepted", len(scores)))
    except Exception as exc:  # noqa: BLE001
        log.warning("prism.evals: submit failed: %s", exc)
        return 0


def run(db_path: str, collector_url: str, *, limit: int = 500,
        ingest_key: Optional[str] = None, verify=True) -> dict:
    scores = score_recent(db_path, limit=limit)
    accepted = submit(collector_url, scores, ingest_key=ingest_key, verify=verify)
    return {"scored_spans_limit": limit, "scores": len(scores), "accepted": accepted}
