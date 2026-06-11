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

from ..store import Writer, default_db_path
from ..version import SCHEMA_VERSION

log = logging.getLogger("prism.collector")

_writer: Optional[Writer] = None
_keys: dict[str, str] = {}


def _load_keys() -> dict[str, str]:
    raw = os.environ.get("PRISM_INGEST_KEYS", "").strip()
    out = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            app_id, key = pair.split(":", 1)
            out[app_id.strip()] = key.strip()
    return out


def _check_key(x_prism_key: Optional[str]) -> None:
    if not _keys:  # open dev mode
        return
    if x_prism_key not in _keys.values():
        raise HTTPException(status_code=401, detail="invalid X-Prism-Key")


def create_app(db_path: Optional[str] = None) -> FastAPI:
    global _writer, _keys
    db_path = db_path or os.environ.get("PRISM_DB", default_db_path())
    _keys = _load_keys()

    api = FastAPI(title="Prism Collector", version="0.1.0")

    @api.on_event("startup")
    def _startup():
        global _writer
        _writer = Writer(db_path).start()
        log.info("prism collector: writing to %s (auth=%s)", db_path, "on" if _keys else "open")

    @api.on_event("shutdown")
    def _shutdown():
        if _writer:
            _writer.shutdown()

    @api.get("/health")
    def health():
        return {"status": "ok", "schema_version": SCHEMA_VERSION, "db": db_path}

    @api.post("/v1/ingest")
    def ingest(payload: dict, x_prism_key: Optional[str] = Header(default=None)):
        _check_key(x_prism_key)
        spans = payload.get("spans") or []
        if not isinstance(spans, list):
            raise HTTPException(status_code=422, detail="spans must be a list")
        _normalize(spans, payload.get("schema_version"))
        _writer.submit_spans(spans)
        return {"accepted": len(spans)}

    @api.post("/v1/scores")
    def scores(payload: dict, x_prism_key: Optional[str] = Header(default=None)):
        _check_key(x_prism_key)
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
