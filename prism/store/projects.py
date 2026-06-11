"""Projects (tenants) + ingest-key management.

Each project is a client/tenant with a unique ingest key. The collector maps an
incoming ``X-Prism-Key`` to a ``project_id`` and stamps it on spans server-side, so
products never send a project id — they just use their key. Project management is an
infrequent admin operation, so it uses short-lived WAL connections (busy_timeout
handles the rare overlap with the collector's writer).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from . import db


def new_project_id() -> str:
    return "prj_" + secrets.token_hex(6)


def new_ingest_key() -> str:
    return "pk_" + secrets.token_urlsafe(24)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProjectsDAO:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def create(self, name: str) -> dict:
        db.init_db(self.db_path)
        proj = {"project_id": new_project_id(), "name": name,
                "ingest_key": new_ingest_key(), "active": 1, "created_at": _now()}
        conn = db.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO projects (project_id, name, ingest_key, active, created_at) "
                "VALUES (?,?,?,?,?)",
                (proj["project_id"], proj["name"], proj["ingest_key"], 1, proj["created_at"]))
            conn.commit()
        finally:
            conn.close()
        return proj

    def list(self) -> list[dict]:
        db.init_db(self.db_path)
        conn = db.connect(self.db_path, read_only=True)
        try:
            return [dict(r) for r in conn.execute(
                "SELECT project_id, name, active, created_at FROM projects "
                "ORDER BY created_at")]
        finally:
            conn.close()

    def key_map(self) -> dict[str, str]:
        """active ingest_key -> project_id."""
        try:
            conn = db.connect(self.db_path, read_only=True)
        except Exception:  # noqa: BLE001 — db may not exist yet
            return {}
        try:
            return {r["ingest_key"]: r["project_id"] for r in conn.execute(
                "SELECT ingest_key, project_id FROM projects WHERE active = 1")}
        finally:
            conn.close()
