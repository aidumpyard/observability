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


def score_recent(db_path: str, limit: int = 500, judge=None, sample: float = 1.0,
                 references: dict | None = None, skip_judged: bool = False,
                 max_judge: int | None = None) -> list[dict]:
    """Heuristic-score the most recent llm spans; optionally LLM-judge (sampled) and
    reference-score (ROUGE-L). For scheduled runs:
      - ``skip_judged`` skips spans already judged (incremental — only new spans),
      - ``max_judge`` caps judge calls this cycle (cost budget).
    Heuristics + reference scoring are cheap and always run."""
    import random
    from . import reference as _ref
    spans = dao.recent_spans(db_path, limit=limit)
    already = dao.judged_span_ids(db_path) if (judge is not None and skip_judged) else set()
    budget = max_judge
    scores: list[dict] = []
    for sp in spans:
        scores.extend(score_span(sp))
        if references:
            scores.extend(_ref.score_span(sp, references))
        if judge is None or sp.get("type") != "llm":
            continue
        if sp.get("span_id") in already:
            continue
        if budget is not None and budget <= 0:
            continue
        if random.random() > sample:
            continue
        try:
            scores.extend(judge.score_span(sp))
            if budget is not None:
                budget -= 1
        except Exception as exc:  # noqa: BLE001 — a judge failure must not kill the batch
            log.debug("prism.evals: judge failed on %s: %s", sp.get("span_id"), exc)
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
        ingest_key: Optional[str] = None, verify=True, judge=None, sample: float = 1.0,
        references: dict | None = None, skip_judged: bool = False,
        max_judge: int | None = None) -> dict:
    scores = score_recent(db_path, limit=limit, judge=judge, sample=sample,
                          references=references, skip_judged=skip_judged, max_judge=max_judge)
    accepted = submit(collector_url, scores, ingest_key=ingest_key, verify=verify)
    return {"scored_spans_limit": limit, "scores": len(scores), "accepted": accepted,
            "judge": bool(judge), "references": len(references or {})}


def run_loop(db_path: str, collector_url: str, *, interval: float = 300.0, **kwargs) -> None:
    """Scheduled evals: run every ``interval`` seconds. Incremental by default
    (skip_judged=True) so each cycle only judges *new* spans — bounding judge cost."""
    import time
    kwargs.setdefault("skip_judged", True)
    log.info("prism eval loop: every %.0fs (Ctrl-C to stop)", interval)
    print(f"prism eval loop: every {interval:.0f}s — incremental (Ctrl-C to stop)")
    try:
        while True:
            res = run(db_path, collector_url, **kwargs)
            print(f"  cycle: scored={res['scores']} accepted={res['accepted']} "
                  f"judge={res['judge']} references={res['references']}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("eval loop stopped")
