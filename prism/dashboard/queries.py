"""Read-only queries that back the dashboard.

All use a read-only WAL connection so the dashboard never contends with the
collector's single writer. Product metrics exclude ``internal='eval'`` spans so
eval traffic doesn't pollute cost/latency/quality numbers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ..store import db

# Only real product LLM calls count toward RED + cost.
_LLM = "type='llm' AND (internal IS NULL OR internal <> 'eval')"

# Robust event time: prefer producer created_at, fall back to started_at, then the
# collector's received_at — so spans never vanish from time-windowed views.
_T = "COALESCE(created_at, started_at, received_at)"


def _cutoff(hours: Optional[int]) -> Optional[str]:
    if not hours:
        return None
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.isoformat().replace("+00:00", "Z")


def _where(app: Optional[str], hours: Optional[int], base: str = _LLM,
           project: Optional[str] = None) -> tuple[str, list]:
    clauses = [base]
    params: list = []
    if project and project != "(all)":
        clauses.append("project_id = ?")
        params.append(project)
    if app and app != "(all)":
        clauses.append("app_id = ?")
        params.append(app)
    cut = _cutoff(hours)
    if cut:
        clauses.append(f"{_T} >= ?")
        params.append(cut)
    return " AND ".join(clauses), params


def list_apps(db_path: str, project: Optional[str] = None) -> list[str]:
    conn = db.connect(db_path, read_only=True)
    try:
        if project and project != "(all)":
            rows = conn.execute("SELECT DISTINCT app_id FROM spans WHERE app_id IS NOT NULL "
                                "AND project_id = ? ORDER BY app_id", (project,)).fetchall()
        else:
            rows = conn.execute("SELECT DISTINCT app_id FROM spans WHERE app_id IS NOT NULL "
                                "ORDER BY app_id").fetchall()
        return [r["app_id"] for r in rows]
    finally:
        conn.close()


def list_projects(db_path: str) -> list[dict]:
    """Projects for the filter: prefer the projects table (names); fall back to
    distinct project_id seen on spans (covers data ingested in open dev mode)."""
    conn = db.connect(db_path, read_only=True)
    try:
        named = {r["project_id"]: r["name"] for r in conn.execute(
            "SELECT project_id, name FROM projects").fetchall()}
        seen = [r["project_id"] for r in conn.execute(
            "SELECT DISTINCT project_id FROM spans WHERE project_id IS NOT NULL "
            "ORDER BY project_id").fetchall()]
        ids = list(dict.fromkeys(list(named) + seen))
        return [{"project_id": pid, "name": named.get(pid, pid)} for pid in ids]
    except Exception:  # noqa: BLE001 — projects table may not exist on old DBs
        return []
    finally:
        conn.close()


def overview(db_path: str, app: Optional[str] = None, hours: int = 24,
             project: Optional[str] = None) -> dict:
    where, params = _where(app, hours, project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        row = conn.execute(
            f"SELECT COUNT(*) calls, COALESCE(SUM(total_tokens),0) tokens, "
            f"COALESCE(SUM(cost_usd),0) cost, COALESCE(AVG(duration_ms),0) avg_ms, "
            f"COALESCE(SUM(status='error'),0) errors FROM spans WHERE {where}", params
        ).fetchone()
        durs = [r[0] for r in conn.execute(
            f"SELECT duration_ms FROM spans WHERE {where} AND duration_ms IS NOT NULL",
            params).fetchall()]
        traces = conn.execute(
            f"SELECT COUNT(DISTINCT trace_id) n FROM spans WHERE {where}", params).fetchone()["n"]
    finally:
        conn.close()
    calls = row["calls"] or 0
    out = dict(row)
    out["traces"] = traces
    out["error_rate"] = round(100.0 * (row["errors"] or 0) / calls, 2) if calls else 0.0
    out["p50_ms"] = _pct(durs, 50)
    out["p95_ms"] = _pct(durs, 95)
    return out


def _pct(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 1)


def timeseries(db_path: str, app: Optional[str] = None, hours: int = 24,
               project: Optional[str] = None) -> list[dict]:
    where, params = _where(app, hours, project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        # hourly buckets via substr on the ISO timestamp (YYYY-MM-DDTHH)
        rows = conn.execute(
            f"SELECT substr({_T},1,13) bucket, COUNT(*) calls, "
            f"COALESCE(SUM(total_tokens),0) tokens, COALESCE(SUM(cost_usd),0) cost, "
            f"COALESCE(SUM(status='error'),0) errors "
            f"FROM spans WHERE {where} GROUP BY bucket ORDER BY bucket", params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def by_app(db_path: str, hours: int = 24, project: Optional[str] = None) -> list[dict]:
    where, params = _where(None, hours, project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            f"SELECT app_id, COUNT(*) calls, COALESCE(SUM(total_tokens),0) tokens, "
            f"COALESCE(SUM(cost_usd),0) cost, ROUND(COALESCE(AVG(duration_ms),0),1) avg_ms, "
            f"COALESCE(SUM(status='error'),0) errors "
            f"FROM spans WHERE {where} GROUP BY app_id ORDER BY calls DESC", params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def by_model(db_path: str, app: Optional[str] = None, hours: int = 24,
             project: Optional[str] = None) -> list[dict]:
    where, params = _where(app, hours, project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            f"SELECT COALESCE(model,'(unknown)') model, COUNT(*) calls, "
            f"COALESCE(SUM(total_tokens),0) tokens, COALESCE(SUM(cost_usd),0) cost "
            f"FROM spans WHERE {where} GROUP BY model ORDER BY cost DESC", params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def by_prompt(db_path: str, app: Optional[str] = None, hours: int = 24,
              project: Optional[str] = None) -> list[dict]:
    """Per prompt-version metrics — enables prompt A/B and regression spotting."""
    where, params = _where(app, hours, project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            f"SELECT prompt_id, COUNT(*) calls, "
            f"COALESCE(SUM(total_tokens),0) tokens, "
            f"ROUND(COALESCE(AVG(duration_ms),0),1) avg_ms, "
            f"COALESCE(SUM(status='error'),0) errors "
            f"FROM spans WHERE {where} AND prompt_id IS NOT NULL "
            f"GROUP BY prompt_id ORDER BY calls DESC", params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def quality_summary(db_path: str, app: Optional[str] = None, hours: int = 24,
                    project: Optional[str] = None) -> list[dict]:
    """Average score per metric name (judge + heuristic), scoped, via scores⋈spans."""
    where, params = _where(app, hours, base="1=1", project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            f"SELECT sc.name, sc.source, ROUND(AVG(sc.value),2) avg, COUNT(*) n "
            f"FROM scores sc JOIN spans s ON sc.span_id = s.span_id "
            f"WHERE {where} GROUP BY sc.name, sc.source ORDER BY sc.source, sc.name",
            params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def quality_by_prompt(db_path: str, app: Optional[str] = None, hours: int = 24,
                      project: Optional[str] = None) -> list[dict]:
    """Average LLM-judge score per prompt version — quality A/B across prompts."""
    where, params = _where(app, hours, base="1=1", project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            f"SELECT s.prompt_id, "
            f"  ROUND(AVG(CASE WHEN sc.name='judge_relevance' THEN sc.value END),2) relevance, "
            f"  ROUND(AVG(CASE WHEN sc.name='judge_coherence' THEN sc.value END),2) coherence, "
            f"  ROUND(AVG(CASE WHEN sc.name='judge_safety' THEN sc.value END),2) safety, "
            f"  COUNT(DISTINCT sc.span_id) graded "
            f"FROM scores sc JOIN spans s ON sc.span_id = s.span_id "
            f"WHERE {where} AND sc.source='llm_judge' AND s.prompt_id IS NOT NULL "
            f"GROUP BY s.prompt_id ORDER BY graded DESC", params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def prompt_usage(db_path: str, ref: str) -> dict:
    """All-time usage for one prompt ref (e.g. 'loan_agent/extract@v1')."""
    conn = db.connect(db_path, read_only=True)
    try:
        row = conn.execute(
            "SELECT COUNT(*) calls, COALESCE(SUM(total_tokens),0) tokens, "
            "ROUND(COALESCE(AVG(duration_ms),0),1) avg_ms, "
            "COALESCE(SUM(status='error'),0) errors FROM spans WHERE prompt_id = ?",
            (ref,)).fetchone()
        return dict(row) if row else {"calls": 0, "tokens": 0, "avg_ms": 0, "errors": 0}
    finally:
        conn.close()


def recent_traces(db_path: str, app: Optional[str] = None, hours: int = 24,
                  limit: int = 100, project: Optional[str] = None) -> list[dict]:
    # Aggregate over ALL spans (not just llm) so trace rows include chain/tool too.
    where, params = _where(app, hours, base="1=1", project=project)
    conn = db.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            f"SELECT trace_id, MAX(app_id) app_id, MAX(project_id) project_id, "
            f"  MIN(CASE WHEN parent_span_id IS NULL THEN name END) name, "
            f"  MIN(started_at) started_at, MAX(ended_at) ended_at, "
            f"  COUNT(*) spans, "
            f"  COALESCE(SUM(CASE WHEN type='llm' THEN total_tokens END),0) tokens, "
            f"  COALESCE(SUM(cost_usd),0) cost, "
            f"  COALESCE(SUM(status='error'),0) errors "
            f"FROM spans WHERE {where} GROUP BY trace_id "
            f"ORDER BY started_at DESC LIMIT ?", params + [limit]).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["duration_ms"] = _span_ms(d["started_at"], d["ended_at"])
            d["status"] = "error" if d["errors"] else "ok"
            d["cost"] = round(d["cost"], 6)
            out.append(d)
        return out
    finally:
        conn.close()


def trace_spans(db_path: str, trace_id: str) -> list[dict]:
    conn = db.connect(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT span_id, parent_span_id, trace_id, type, name, model, prompt_id, "
            "started_at, ended_at, duration_ms, prompt_tokens, completion_tokens, "
            "total_tokens, cost_usd, status, error, system_prompt, user_message, response_text "
            "FROM spans WHERE trace_id = ? ORDER BY started_at ASC", (trace_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _span_ms(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return round((b - a).total_seconds() * 1000.0, 1)
    except Exception:  # noqa: BLE001
        return None
