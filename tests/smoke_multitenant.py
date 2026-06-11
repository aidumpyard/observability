"""Multi-tenant smoke: two projects, two keys, spans stamped with the right
project_id server-side; strict mode rejects unknown keys. Uses FastAPI TestClient
(no uvicorn)."""

import os
import tempfile
import time

from fastapi.testclient import TestClient

from prism.store import ProjectsDAO, dao
from prism.version import SCHEMA_VERSION


def _span(span_id, app):
    return {"span_id": span_id, "trace_id": "t_" + span_id, "type": "llm", "name": "x",
            "app_id": app, "total_tokens": 10, "status": "ok", "schema_version": SCHEMA_VERSION,
            "started_at": "2026-06-11T10:00:00Z", "created_at": "2026-06-11T10:00:00Z"}


def main():
    db_path = os.path.join(tempfile.mkdtemp(), "mt.db")
    os.environ["PRISM_DB"] = db_path
    os.environ["PRISM_REQUIRE_KEY"] = "1"   # strict mode

    projects = ProjectsDAO(db_path)
    a = projects.create("acme")
    b = projects.create("globex")
    print("created:", a["project_id"], b["project_id"])

    from prism.collector.app import create_app
    app = create_app(db_path)

    with TestClient(app) as client:
        # valid keys -> accepted + project stamped
        r = client.post("/v1/ingest", json={"schema_version": SCHEMA_VERSION, "spans": [_span("s1", "app1")]},
                        headers={"X-Prism-Key": a["ingest_key"]})
        assert r.status_code == 200, r.text
        assert r.json()["project_id"] == a["project_id"], r.json()

        r = client.post("/v1/ingest", json={"schema_version": SCHEMA_VERSION, "spans": [_span("s2", "app2")]},
                        headers={"X-Prism-Key": b["ingest_key"]})
        assert r.json()["project_id"] == b["project_id"]

        # unknown key -> 401 in strict mode
        r = client.post("/v1/ingest", json={"schema_version": SCHEMA_VERSION, "spans": [_span("s3", "app3")]},
                        headers={"X-Prism-Key": "pk_bogus"})
        assert r.status_code == 401, r.status_code

        # missing key -> 401 in strict mode
        r = client.post("/v1/ingest", json={"schema_version": SCHEMA_VERSION, "spans": [_span("s4", "app4")]})
        assert r.status_code == 401, r.status_code

        # projects endpoint
        r = client.get("/v1/projects")
        assert len(r.json()["projects"]) == 2

    time.sleep(0.8)  # writer commit

    spans = {s["span_id"]: s for s in dao.recent_spans(db_path, limit=10)}
    assert spans["s1"]["project_id"] == a["project_id"], spans["s1"]["project_id"]
    assert spans["s2"]["project_id"] == b["project_id"]
    assert "s3" not in spans and "s4" not in spans, "rejected spans must not persist"

    os.environ.pop("PRISM_REQUIRE_KEY", None)
    print("✅ MULTITENANT OK — per-project keys, server-side project_id stamping, strict 401, isolation")


if __name__ == "__main__":
    main()
