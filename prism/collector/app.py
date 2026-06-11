"""The Prism collector — the fan-in point and the ONLY SQLite writer.

Run with a single worker (decision B1):
    uvicorn prism.collector:app --host 0.0.0.0 --port 9100 \
        --ssl-keyfile ~/.prism/key.pem --ssl-certfile ~/.prism/cert.pem

Request handlers only hand work to the single Writer thread; they never touch the
DB directly. Per-app ingest keys are checked against PRISM_INGEST_KEYS
(comma-separated "app:key" pairs); if unset, auth is open (dev mode).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException

from ..store import ProjectsDAO, Writer, default_db_path
from ..version import SCHEMA_VERSION

log = logging.getLogger("prism.collector")

_writer: Optional[Writer] = None
_projects: Optional[ProjectsDAO] = None
_keymap: dict[str, str] = {}          # ingest_key -> project_id
_require_key: bool = False


def _reload_keymap() -> None:
    global _keymap
    out = dict(_projects.key_map()) if _projects else {}
    # Back-compat: env "PRISM_INGEST_KEYS" as "project_id:key" pairs.
    raw = os.environ.get("PRISM_INGEST_KEYS", "").strip()
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            pid, key = pair.split(":", 1)
            out[key.strip()] = pid.strip()
    _keymap = out


def _resolve_project(x_prism_key: Optional[str]) -> Optional[str]:
    """Map an ingest key to a project_id, reloading once on a miss."""
    if x_prism_key and x_prism_key in _keymap:
        return _keymap[x_prism_key]
    if x_prism_key:
        _reload_keymap()
        if x_prism_key in _keymap:
            return _keymap[x_prism_key]
    if _require_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-Prism-Key")
    return None  # open dev mode: accept, project_id stays null


def create_app(db_path: Optional[str] = None) -> FastAPI:
    global _writer, _projects, _require_key
    db_path = db_path or os.environ.get("PRISM_DB", default_db_path())
    _projects = ProjectsDAO(db_path)
    _require_key = os.environ.get("PRISM_REQUIRE_KEY", "").lower() in ("1", "true", "yes")

    api = FastAPI(title="Prism Collector", version="0.1.0")

    @api.on_event("startup")
    def _startup():
        global _writer
        _writer = Writer(db_path).start()
        _reload_keymap()
        log.info("prism collector: writing to %s (projects=%d, strict=%s)",
                 db_path, len(_keymap), _require_key)

    @api.on_event("shutdown")
    def _shutdown():
        if _writer:
            _writer.shutdown()

    @api.get("/health")
    def health():
        return {"status": "ok", "schema_version": SCHEMA_VERSION, "db": db_path}

    @api.post("/v1/ingest")
    def ingest(payload: dict, x_prism_key: Optional[str] = Header(default=None)):
        project_id = _resolve_project(x_prism_key)
        spans = payload.get("spans") or []
        if not isinstance(spans, list):
            raise HTTPException(status_code=422, detail="spans must be a list")
        _normalize(spans, payload.get("schema_version"))
        if project_id:                       # stamp tenant server-side
            for s in spans:
                s["project_id"] = project_id
        _writer.submit_spans(spans)
        return {"accepted": len(spans), "project_id": project_id}

    @api.get("/v1/projects")
    def list_projects():
        return {"projects": _projects.list() if _projects else []}

    @api.post("/v1/scores")
    def scores(payload: dict, x_prism_key: Optional[str] = Header(default=None)):
        _resolve_project(x_prism_key)
        items = payload.get("scores") or []
        if not isinstance(items, list):
            raise HTTPException(status_code=422, detail="scores must be a list")
        _writer.submit_scores(items)
        return {"accepted": len(items)}

    return api


def _normalize(spans: list, version: Optional[int]) -> None:
    """Backward-compat layer (decision C3). v1 is identity; future versions
    upgrade older payloads in place here."""
    v = version or SCHEMA_VERSION
    if v == SCHEMA_VERSION:
        return
    # Placeholder for future migrations: e.g. rename fields from v1 -> v2.
    log.debug("prism collector: normalizing payload schema_version=%s", v)


# Module-level app for `uvicorn prism.collector:app`.
app = create_app()
