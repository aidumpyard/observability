"""The single writer (decision B1).

One thread, one write connection, all writes (spans AND scores) funneled through one
in-process queue and committed in batched transactions. The collector's request
handlers only ``submit()`` work here; they never touch SQLite directly. This is what
makes "single writer" true by construction, so concurrent ingest + score writes
never hit SQLITE_BUSY.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Optional

from . import db

log = logging.getLogger("prism.writer")

# Columns we persist for a span, in order.
_SPAN_COLS = [
    "span_id", "trace_id", "parent_span_id", "type", "name", "model", "prompt_id",
    "params_json", "system_prompt", "user_message", "response_text",
    "input_json", "output_json", "attributes_json",
    "prompt_tokens", "completion_tokens", "total_tokens", "thoughts_tokens",
    "tokens_source", "finish_reason", "full_gemini_response", "cost_usd",
    "duration_ms", "status", "error", "data_classification", "response_id",
    "project_id", "app_id", "env", "app_type", "internal", "schema_version",
    "started_at", "ended_at", "created_at", "received_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _span_row(span: dict) -> list:
    received_at = _now()  # collector clock — used for skew correction (B5)
    return [
        span.get("span_id"), span.get("trace_id"), span.get("parent_span_id"),
        span.get("type"), span.get("name"), span.get("model"), span.get("prompt_id"),
        _dumps(span.get("params")), span.get("system_prompt"), span.get("user_message"),
        span.get("response_text"),
        _dumps(span.get("input")), _dumps(span.get("output")), _dumps(span.get("attributes")),
        span.get("prompt_tokens"), span.get("completion_tokens"), span.get("total_tokens"),
        span.get("thoughts_tokens"), span.get("tokens_source"), span.get("finish_reason"),
        span.get("full_gemini_response"), span.get("cost_usd"), span.get("duration_ms"),
        span.get("status"), span.get("error"), span.get("data_classification"),
        span.get("response_id"), span.get("project_id"),
        span.get("app_id"), span.get("env"), span.get("app_type"),
        span.get("internal"), span.get("schema_version"),
        span.get("started_at"), span.get("ended_at"), span.get("created_at"), received_at,
    ]


def _dumps(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        return val
    try:
        return json.dumps(val, default=str)
    except Exception:  # noqa: BLE001
        return str(val)


class Writer:
    def __init__(self, db_path: str, batch_size: int = 200, flush_interval: float = 0.5):
        self.db_path = db_path
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.q: queue.Queue[tuple] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="prism-writer", daemon=True)
        self._conn = None

    def start(self) -> "Writer":
        db.init_db(self.db_path)
        self._conn = db.connect(self.db_path)
        self._thread.start()
        return self

    # -- API used by collector handlers --
    def submit_spans(self, spans: list[dict]) -> None:
        for s in spans:
            self.q.put(("span", s))

    def submit_scores(self, scores: list[dict]) -> None:
        for s in scores:
            self.q.put(("score", s))

    # -- background drain --
    def _run(self) -> None:
        import time
        pending: list[tuple] = []
        last = time.monotonic()
        while not self._stop.is_set() or not self.q.empty():
            try:
                pending.append(self.q.get(timeout=self.flush_interval))
            except queue.Empty:
                pass
            due = (time.monotonic() - last) >= self.flush_interval
            if pending and (len(pending) >= self.batch_size or due):
                self._commit(pending)
                pending = []
                last = time.monotonic()
        if pending:
            self._commit(pending)

    def _commit(self, items: list[tuple]) -> None:
        spans = [i[1] for i in items if i[0] == "span"]
        scores = [i[1] for i in items if i[0] == "score"]
        try:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            if spans:
                placeholders = ",".join(["?"] * len(_SPAN_COLS))
                cols = ",".join(_SPAN_COLS)
                cur.executemany(
                    f"INSERT OR REPLACE INTO spans ({cols}) VALUES ({placeholders})",
                    [_span_row(s) for s in spans],
                )
                self._upsert_apps(cur, spans)
                self._recompute_traces(cur, {s.get("trace_id") for s in spans if s.get("trace_id")})
            if scores:
                # Upsert: one score per (span_id, name, source); a re-run replaces.
                cur.executemany(
                    "INSERT INTO scores (span_id, trace_id, name, value, label, source, "
                    "rationale, created_at) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(span_id, name, source) DO UPDATE SET "
                    "value=excluded.value, label=excluded.label, "
                    "rationale=excluded.rationale, trace_id=excluded.trace_id, "
                    "created_at=excluded.created_at",
                    [(s.get("span_id"), s.get("trace_id"), s.get("name"), s.get("value"),
                      s.get("label"), s.get("source"), s.get("rationale"),
                      s.get("created_at") or _now()) for s in scores],
                )
            self._conn.commit()
        except Exception:  # noqa: BLE001 — writer must never die
            log.exception("prism.writer: commit failed; rolling back")
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001
                pass

    def _upsert_apps(self, cur, spans: list[dict]) -> None:
        seen = {}
        for s in spans:
            aid = s.get("app_id")
            if aid and aid not in seen:
                seen[aid] = s.get("app_type")
        for aid, atype in seen.items():
            cur.execute(
                "INSERT OR IGNORE INTO apps (app_id, name, owner, created_at) VALUES (?,?,?,?)",
                (aid, aid, atype, _now()),
            )

    def _recompute_traces(self, cur, trace_ids: set) -> None:
        """Derive trace bounds from spans (decision B5: no single 'trace end' event)."""
        for tid in trace_ids:
            cur.execute(
                """
                INSERT INTO traces (trace_id, app_id, user_id, session_id, name, status,
                                    started_at, ended_at, duration_ms)
                SELECT
                    ?, MAX(app_id), NULL, NULL,
                    COALESCE(MIN(CASE WHEN parent_span_id IS NULL THEN name END), MIN(name)),
                    CASE WHEN SUM(status = 'error') > 0 THEN 'error' ELSE 'ok' END,
                    MIN(started_at), MAX(ended_at),
                    (julianday(MAX(REPLACE(ended_at, 'Z', '')))
                     - julianday(MIN(REPLACE(started_at, 'Z', '')))) * 86400000.0
                FROM spans WHERE trace_id = ?
                ON CONFLICT(trace_id) DO UPDATE SET
                    app_id=excluded.app_id, name=excluded.name, status=excluded.status,
                    started_at=excluded.started_at, ended_at=excluded.ended_at,
                    duration_ms=excluded.duration_ms
                """,
                (tid, tid),
            )

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)
        if self._conn:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
