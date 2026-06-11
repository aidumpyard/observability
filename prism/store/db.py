"""SQLite connection + schema bootstrap.

WAL mode lets the dashboard and eval engine read concurrently while the collector's
single writer thread writes (decision B1). ``busy_timeout`` turns any rare
contention into a short retry instead of a SQLITE_BUSY error.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_SCHEMA = Path(__file__).with_name("schema.sql")


def default_db_path() -> str:
    base = os.environ.get("PRISM_HOME", os.path.expanduser("~/.prism"))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "prism.db")


def connect(db_path: str, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(_SCHEMA.read_text())
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn) -> None:
    """Additive migrations for DBs created before a column/index existed."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(spans)")}
    if "project_id" not in cols:
        conn.execute("ALTER TABLE spans ADD COLUMN project_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_project ON spans(project_id)")

    # Idempotent scores: at most one score per (span_id, name, source). De-dupe any
    # existing rows (keep the newest), then add the unique index that upserts rely on.
    idx = {r["name"] for r in conn.execute("PRAGMA index_list(scores)")}
    if "idx_scores_unique" not in idx:
        conn.execute(
            "DELETE FROM scores WHERE span_id IS NOT NULL AND score_id NOT IN "
            "(SELECT MAX(score_id) FROM scores WHERE span_id IS NOT NULL "
            " GROUP BY span_id, name, source)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_scores_unique "
                     "ON scores(span_id, name, source)")
