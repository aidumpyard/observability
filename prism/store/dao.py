"""Read-only queries for the dashboard and eval engine.

These open a read-only WAL connection so they never contend with the single writer.
Kept deliberately small for Phase 1 — enough to verify the spine and back the first
dashboard views.
"""

from __future__ import annotations

from typing import Optional

from . import db


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def recent_spans(db_path: str, limit: int = 100, app_id: Optional[str] = None) -> list[dict]:
    conn = db.connect(db_path, read_only=True)
    try:
        if app_id:
            return _rows(conn,
                "SELECT * FROM spans WHERE app_id=? ORDER BY created_at DESC LIMIT ?",
                (app_id, limit))
        return _rows(conn, "SELECT * FROM spans ORDER BY created_at DESC LIMIT ?", (limit,))
    finally:
        conn.close()


def trace_spans(db_path: str, trace_id: str) -> list[dict]:
    conn = db.connect(db_path, read_only=True)
    try:
        return _rows(conn,
            "SELECT * FROM spans WHERE trace_id=? ORDER BY started_at ASC", (trace_id,))
    finally:
        conn.close()


def summary(db_path: str) -> dict:
    """Headline RED + cost numbers, excluding internal=eval traffic."""
    conn = db.connect(db_path, read_only=True)
    try:
        base = "FROM spans WHERE type='llm' AND (internal IS NULL OR internal <> 'eval')"
        row = conn.execute(
            f"SELECT COUNT(*) calls, "
            f"SUM(total_tokens) tokens, SUM(cost_usd) cost, "
            f"AVG(duration_ms) avg_ms, "
            f"SUM(status='error') errors {base}"
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def by_app(db_path: str) -> list[dict]:
    conn = db.connect(db_path, read_only=True)
    try:
        return _rows(conn,
            "SELECT app_id, COUNT(*) calls, SUM(total_tokens) tokens, "
            "SUM(cost_usd) cost, AVG(duration_ms) avg_ms "
            "FROM spans WHERE type='llm' GROUP BY app_id ORDER BY calls DESC")
    finally:
        conn.close()
