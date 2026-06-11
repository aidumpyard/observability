"""Prism dashboard (Dash/Plotly) — the only egress surface in v1.

Three tabs: Overview (RED + cost), Traces (explorer), and a Trace waterfall with
token/cost/latency overlays. A live-tail interval refreshes the data. Reads the
SQLite store read-only, so it never blocks the collector's writer.

Run:  prism dashboard --db ~/.prism/prism.db --port 8050
"""

from __future__ import annotations

import difflib
import os
from typing import Optional


def _envbool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html
from dash.exceptions import PreventUpdate

from ..prompts import PromptRepo, default_root
from ..store import default_db_path
from . import identity as _identity
from . import queries

_TYPE_COLORS = {
    "llm": "#6366f1", "chain": "#0ea5e9", "tool": "#22c55e",
    "retrieval": "#f59e0b", "agent": "#a855f7", "span": "#94a3b8",
}


# --- figure builders (pure functions; unit-testable) -----------------------

_CALLS_C = "#6366f1"
_TOKENS_C = "#10b981"
_COST_C = "#f59e0b"


def build_timeseries(rows: list[dict], show_cost: bool = False, metric: str = "both") -> go.Figure:
    """metric: 'calls' | 'tokens' | 'cost' | 'both'. Uses a real datetime x-axis and
    adaptive bucket size (carried on each row as 'granularity')."""
    if not rows:
        return _empty("no data in window")
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["bucket"], errors="coerce", utc=True)
    df = df.dropna(subset=["t"]).sort_values("t")
    if df.empty:
        return _empty("no data in window")
    gran = df["granularity"].iloc[0] if "granularity" in df else "hour"
    single = (len(df) == 1)

    sec, sec_name, sec_c = (("cost", "cost $", _COST_C) if show_cost
                            else ("tokens", "tokens", _TOKENS_C))
    fig = go.Figure()

    def _calls():
        fig.add_bar(x=df["t"], y=df["calls"], name="calls", marker_color=_CALLS_C, opacity=0.85)

    fills = {_TOKENS_C: "rgba(16,185,129,0.12)", _COST_C: "rgba(245,158,11,0.12)"}

    def _line(col, name, color, y2=False):
        fig.add_scatter(x=df["t"], y=df[col], name=name, mode="lines+markers",
                        line=dict(color=color, width=2, shape="spline"),
                        marker=dict(size=8 if single else 5),
                        fill=None if y2 else "tozeroy",
                        fillcolor=None if y2 else fills.get(color),
                        yaxis="y2" if y2 else "y")

    if metric == "calls":
        _calls()
        fig.update_layout(yaxis=dict(title="calls"))
    elif metric in ("tokens", "cost"):
        col = "cost" if (metric == "cost" and show_cost) else "tokens"
        _line(col, col, _TOKENS_C if col == "tokens" else _COST_C)
        fig.update_layout(yaxis=dict(title=col))
    else:  # both
        _calls()
        _line(sec, sec_name, sec_c, y2=True)
        fig.update_layout(yaxis=dict(title="calls"),
                          yaxis2=dict(title=sec_name, overlaying="y", side="right", showgrid=False))

    tickfmt = {"minute": "%H:%M", "hour": "%b %d %H:%M", "day": "%b %d"}.get(gran, "%b %d %H:%M")
    fig.update_layout(
        margin=dict(l=45, r=45, t=28, b=30), height=300, template="plotly_white",
        hovermode="x unified", bargap=0.25,
        legend=dict(orientation="h", y=1.15, x=0),
        xaxis=dict(title=None, tickformat=tickfmt, showgrid=True, gridcolor="#eef2f7"),
    )
    return fig


def build_model_bar(rows: list[dict], show_cost: bool = False) -> go.Figure:
    if not rows:
        return _empty("no model data")
    df = pd.DataFrame(rows)
    metric = "cost" if show_cost else "tokens"
    fig = px.bar(df, x="model", y=metric, hover_data=["calls"],
                 title=None, template="plotly_white")
    fig.update_layout(margin=dict(l=40, r=20, t=20, b=30), height=300,
                      yaxis_title=("cost $" if show_cost else "tokens"))
    return fig


def build_waterfall(spans: list[dict]) -> go.Figure:
    """Gantt-style timeline of a trace's spans, colored by type."""
    if not spans:
        return _empty("select a trace")
    rows = []
    for s in spans:
        start = _parse(s.get("started_at"))
        if start is None:
            continue
        dur = s.get("duration_ms") or 0
        end = start + pd.to_timedelta(max(dur, 0.5), unit="ms")
        label = f"{s['type']}:{s['name']}"
        tok = s.get("total_tokens")
        cost = s.get("cost_usd")
        rows.append(dict(
            Span=label, Start=start, Finish=end, Type=s["type"],
            dur=dur, tokens=tok, cost=cost, status=s.get("status"),
            span_id=s["span_id"][:8],
        ))
    if not rows:
        return _empty("no timing data for this trace")
    df = pd.DataFrame(rows)
    fig = px.timeline(
        df, x_start="Start", x_end="Finish", y="Span", color="Type",
        color_discrete_map=_TYPE_COLORS,
        hover_data={"dur": ":.1f", "tokens": True, "cost": ":.6f",
                    "status": True, "Start": False, "Finish": False},
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(margin=dict(l=20, r=20, t=20, b=30),
                      height=max(260, 36 * len(rows)), template="plotly_white",
                      legend=dict(orientation="h", y=1.05))
    return fig


def _pre(text: str, bg: str) -> html.Pre:
    return html.Pre(text or "—", style={
        "whiteSpace": "pre-wrap", "wordBreak": "break-word", "margin": "4px 0",
        "padding": "8px 10px", "background": bg, "borderRadius": "6px",
        "fontSize": "12px", "maxHeight": "260px", "overflow": "auto",
    })


def build_messages(spans: list[dict]) -> list:
    """Collapsible System / Prompt / Response per LLM span (native <details>)."""
    blocks = []
    llm = [s for s in spans if s.get("type") == "llm"
           or s.get("user_message") or s.get("response_text")]
    if not llm:
        return [html.Div("no captured prompts/responses for this trace "
                         "(capture_io disabled?)", style={"color": "#94a3b8"})]
    for s in llm:
        toks = s.get("total_tokens")
        summary = f"🧠 {s.get('name','llm')}"
        if s.get("prompt_id"):
            summary += f"  ·  {s['prompt_id']}"
        if toks:
            summary += f"  ·  {toks} tok"
        if s.get("status") == "error":
            summary += "  ·  ⚠ error"
        children = []
        if s.get("system_prompt"):
            children += [html.Div("SYSTEM", style={"fontSize": "11px", "color": "#64748b", "marginTop": "6px"}),
                         _pre(s["system_prompt"], "#f1f5f9")]
        children += [html.Div("PROMPT", style={"fontSize": "11px", "color": "#64748b", "marginTop": "6px"}),
                     _pre(s.get("user_message"), "#eff6ff")]
        children += [html.Div("RESPONSE", style={"fontSize": "11px", "color": "#64748b", "marginTop": "6px"}),
                     _pre(s.get("response_text"), "#f0fdf4")]
        if s.get("error"):
            children += [_pre(s["error"], "#fef2f2")]
        blocks.append(html.Details(open=False, style={
            "border": "1px solid #e2e8f0", "borderRadius": "8px", "padding": "8px 10px", "marginBottom": "8px"},
            children=[html.Summary(summary, style={"cursor": "pointer", "fontWeight": 600, "fontSize": "13px"}),
                      html.Div(children)]))
    return blocks


def _empty(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(height=260, template="plotly_white",
                      annotations=[dict(text=msg, showarrow=False, font=dict(size=14, color="#888"))],
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def _parse(iso: Optional[str]):
    if not iso:
        return None
    try:
        return pd.to_datetime(iso, utc=True)
    except Exception:  # noqa: BLE001
        return None


# --- card helper -----------------------------------------------------------

def _card(title: str, value: str, sub: str = "") -> html.Div:
    return html.Div(className="prism-card", style={
        "background": "white", "borderRadius": "10px", "padding": "14px 18px",
        "boxShadow": "0 1px 3px rgba(0,0,0,.08)", "flex": "1", "minWidth": "140px",
    }, children=[
        html.Div(title, style={"fontSize": "12px", "color": "#64748b", "textTransform": "uppercase"}),
        html.Div(value, style={"fontSize": "26px", "fontWeight": "700", "color": "#0f172a"}),
        html.Div(sub, style={"fontSize": "12px", "color": "#94a3b8"}),
    ])


# --- app factory -----------------------------------------------------------

def create_app(db_path: Optional[str] = None, show_cost: bool = False,
               prompts_root: Optional[str] = None,
               show_waterfall: Optional[bool] = None,
               show_quality: Optional[bool] = None) -> Dash:
    db_path = db_path or default_db_path()
    prompts_root = prompts_root or default_root()
    # config toggles (param overrides env; env overrides default)
    if show_waterfall is None:
        show_waterfall = _envbool("PRISM_SHOW_WATERFALL", True)
    if show_quality is None:
        show_quality = _envbool("PRISM_SHOW_QUALITY", True)
    app = Dash(__name__, title="Prism", suppress_callback_exceptions=True)

    from flask import jsonify

    @app.server.route("/auth/detail")
    def _auth_detail():                # GET /auth/detail -> {"identities":[...]}
        return jsonify({"identities": _identity.names()})

    app.layout = html.Div(style={"background": "#f1f5f9", "minHeight": "100vh",
                                 "fontFamily": "Inter, system-ui, sans-serif", "padding": "16px 24px"},
        children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "16px"}, children=[
                html.H2("🔭 Prism", style={"margin": 0, "color": "#0f172a"}),
                html.Span("identity", style={"fontSize": "12px", "color": "#64748b"}),
                dcc.Dropdown(id="identity",
                             options=[{"label": n, "value": n} for n in _identity.names()],
                             value="admin", clearable=False, style={"width": "150px"}),
                dcc.Dropdown(id="project-filter", placeholder="all projects",
                             value="(all)", clearable=False, style={"width": "200px"}),
                dcc.Dropdown(id="app-filter", placeholder="all apps", style={"width": "200px"}),
                dcc.Dropdown(id="window", options=[
                    {"label": "last 1h", "value": 1}, {"label": "last 24h", "value": 24},
                    {"label": "last 7d", "value": 168}, {"label": "all", "value": 0},
                ], value=24, clearable=False, style={"width": "120px"}),
                dcc.Checklist(id="live", options=[{"label": " live", "value": "on"}],
                              value=["on"], style={"marginLeft": "auto"}),
            ]),
            dcc.Interval(id="tick", interval=5000, n_intervals=0),
            dcc.Store(id="selected-trace"),
            dcc.Tabs(id="tabs", value="overview", children=[
                dcc.Tab(label="Overview", value="overview"),
                dcc.Tab(label="Traces", value="traces"),
                *([dcc.Tab(label="Quality", value="quality")] if show_quality else []),
                dcc.Tab(label="Prompts", value="prompts"),
            ]),
            html.Div(id="tab-body", style={"marginTop": "14px"}),
        ])

    _register(app, db_path, show_cost, prompts_root, show_waterfall, show_quality)
    return app


def _register(app: Dash, db_path: str, show_cost: bool = False,
              prompts_root: Optional[str] = None, show_waterfall: bool = True,
              show_quality: bool = True) -> None:
    repo = PromptRepo(prompts_root)

    @app.callback(Output("project-filter", "options"), Output("project-filter", "value"),
                  Output("project-filter", "disabled"),
                  Input("identity", "value"), Input("tick", "n_intervals"),
                  State("project-filter", "value"))
    def _projects(identity, _, current):
        bound = _identity.project_for(identity)
        rows = queries.list_projects(db_path)
        if bound:  # tenant identity: locked to its project
            name = next((p["name"] for p in rows if p["project_id"] == bound), bound)
            return [{"label": name, "value": bound}], bound, True
        opts = [{"label": "(all projects)", "value": "(all)"}] + \
               [{"label": p["name"], "value": p["project_id"]} for p in rows]
        return opts, (current or "(all)"), False

    @app.callback(Output("app-filter", "options"),
                  Input("project-filter", "value"), Input("tick", "n_intervals"))
    def _apps(project, _):
        return [{"label": "(all)", "value": "(all)"}] + \
               [{"label": a, "value": a} for a in queries.list_apps(db_path, project)]

    @app.callback(Output("tick", "disabled"), Input("live", "value"))
    def _toggle_live(live):
        return "on" not in (live or [])

    @app.callback(
        Output("tab-body", "children"),
        Input("tabs", "value"), Input("tick", "n_intervals"),
        Input("app-filter", "value"), Input("window", "value"),
        Input("project-filter", "value"), Input("identity", "value"),
        Input("selected-trace", "data"),
    )
    def _render(tab, _n, app_id, hours, project, identity, selected):
        ts_metric = "both"   # metric switch removed; default to calls + tokens
        # Tenant identities are locked to their project (enforced server-side).
        project = _identity.project_for(identity) or project
        # Don't let the 5s live-tick rebuild a tab the user is interacting with:
        # the Prompts tab always, and the Traces tab once a trace is open (so the
        # waterfall doesn't flicker/reset every 5s while you inspect it). The traces
        # LIST still live-updates until you drill into one.
        if ctx.triggered_id == "tick":
            if tab == "prompts":
                raise PreventUpdate
            if tab == "traces" and selected:
                raise PreventUpdate
        if tab == "overview":
            return _overview_body(db_path, app_id, hours, show_cost, project, ts_metric)
        if tab == "quality":
            if not show_quality:
                raise PreventUpdate
            return _quality_body(db_path, app_id, hours, project)
        if tab == "prompts":
            return _prompts_body(repo)
        return _traces_body(db_path, app_id, hours, selected, show_cost, project, show_waterfall)

    # ---- Prompts tab: cascading app -> name -> version -> detail ----
    @app.callback(
        Output("pr-name", "options"), Output("pr-name", "value"),
        Input("pr-app", "value"), prevent_initial_call=False)
    def _pr_names(app_id):
        names = repo.list_prompts(app_id) if app_id else []
        return [{"label": n, "value": n} for n in names], (names[0] if names else None)

    @app.callback(
        Output("pr-version", "options"), Output("pr-version", "value"),
        Input("pr-name", "value"), State("pr-app", "value"), prevent_initial_call=False)
    def _pr_versions(name, app_id):
        vers = repo.versions(app_id, name) if (app_id and name) else []
        opts = [{"label": f"v{v}", "value": v} for v in vers]
        return opts, (vers[-1] if vers else None)

    @app.callback(
        Output("pr-detail", "children"),
        Input("pr-version", "value"), State("pr-app", "value"), State("pr-name", "value"))
    def _pr_detail(version, app_id, name):
        if not (app_id and name and version):
            raise PreventUpdate
        return _prompt_detail(repo, db_path, app_id, name, int(version))

    @app.callback(
        Output("selected-trace", "data"),
        Input("traces-table", "active_cell"),
        State("traces-table", "data"),
        prevent_initial_call=True,
    )
    def _select(active, data):
        if active and data:
            return data[active["row"]]["trace_id"]
        return None


def _overview_body(db_path, app_id, hours, show_cost=False, project=None, ts_metric="both"):
    o = queries.overview(db_path, app_id, hours, project)
    cards_list = [
        _card("LLM calls", f"{o['calls']:,}", f"{o['traces']} traces"),
        _card("Tokens", f"{int(o['tokens']):,}"),
        _card("Latency p50/p95", f"{o['p50_ms']:.0f}/{o['p95_ms']:.0f} ms", f"avg {o['avg_ms']:.0f} ms"),
        _card("Error rate", f"{o['error_rate']:.1f}%", f"{o['errors']} errors"),
    ]
    if show_cost:
        cards_list.insert(2, _card("Cost", f"${o['cost']:.4f}"))
    cards = html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=cards_list)

    ts_label = {"calls": "Calls", "tokens": "Tokens"}.get(ts_metric,
               "Calls & cost" if show_cost else "Calls & tokens")
    ts_title = f"{ts_label} over time"
    bar_title = "Cost by model" if show_cost else "Tokens by model"
    charts = html.Div(style={"display": "flex", "gap": "12px", "marginTop": "12px", "flexWrap": "wrap"}, children=[
        html.Div(style={"flex": "2", "minWidth": "420px", "background": "white", "borderRadius": "10px", "padding": "8px"},
                 children=[html.Div(ts_title, style={"padding": "6px 10px", "fontWeight": 600}),
                           dcc.Graph(figure=build_timeseries(queries.timeseries(db_path, app_id, hours, project), show_cost, ts_metric))]),
        html.Div(style={"flex": "1", "minWidth": "320px", "background": "white", "borderRadius": "10px", "padding": "8px"},
                 children=[html.Div(bar_title, style={"padding": "6px 10px", "fontWeight": 600}),
                           dcc.Graph(figure=build_model_bar(queries.by_model(db_path, app_id, hours, project), show_cost))]),
    ])
    rows = queries.by_app(db_path, hours, project)
    app_cols = ["app_id", "calls", "tokens", "cost", "avg_ms", "errors"] if show_cost \
        else ["app_id", "calls", "tokens", "avg_ms", "errors"]
    table = html.Div(style={"marginTop": "12px", "background": "white", "borderRadius": "10px", "padding": "10px"}, children=[
        html.Div("By application", style={"fontWeight": 600, "marginBottom": "6px"}),
        dash_table.DataTable(
            data=rows, columns=[{"name": c, "id": c} for c in app_cols],
            style_cell={"fontFamily": "monospace", "fontSize": "13px", "padding": "6px"},
            style_header={"fontWeight": "700", "background": "#f8fafc"},
        ),
    ])
    prows = queries.by_prompt(db_path, app_id, hours, project)
    ptable = html.Div(style={"marginTop": "12px", "background": "white", "borderRadius": "10px", "padding": "10px"}, children=[
        html.Div("By prompt version", style={"fontWeight": 600, "marginBottom": "6px"}),
        dash_table.DataTable(
            data=prows or [{"prompt_id": "(none — products not yet linked to prompts)"}],
            columns=[{"name": c, "id": c} for c in ["prompt_id", "calls", "tokens", "avg_ms", "errors"]],
            style_cell={"fontFamily": "monospace", "fontSize": "13px", "padding": "6px",
                        "maxWidth": "320px", "overflow": "hidden", "textOverflow": "ellipsis"},
            style_header={"fontWeight": "700", "background": "#f8fafc"},
        ),
    ])
    return html.Div([cards, charts, table, ptable])


def _quality_body(db_path, app_id, hours, project=None):
    summ = queries.quality_summary(db_path, app_id, hours, project)
    by_name = {r["name"]: r for r in summ}

    def metric(name, label):
        r = by_name.get(name)
        return _card(label, f"{r['avg']:.2f}" if r else "—", f"n={r['n']}" if r else "no data")

    cards = [
        metric("judge_relevance", "Relevance (1–5)"),
        metric("judge_coherence", "Coherence (1–5)"),
        metric("judge_safety", "Safety (1–5)"),
        metric("answered", "Answered rate"),
        metric("json_valid", "JSON valid rate"),
    ]
    if "rouge_l" in by_name:   # reference-based regression (only when references exist)
        cards.append(metric("rouge_l", "ROUGE-L (vs reference)"))
    judge_cards = html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=cards)
    if not summ:
        note = html.Div("No scores yet. Run the eval engine: heuristics always, plus the "
                        "LLM-judge if configured (writes to /v1/scores).",
                        style={"color": "#94a3b8", "marginTop": "10px"})
    else:
        note = html.Span()

    name_table = html.Div(style={"marginTop": "12px", "background": "white", "borderRadius": "10px", "padding": "10px"}, children=[
        html.Div("Scores by metric", style={"fontWeight": 600, "marginBottom": "6px"}),
        dash_table.DataTable(
            data=summ or [{"name": "(none)"}],
            columns=[{"name": c, "id": c} for c in ["source", "name", "avg", "n"]],
            style_cell={"fontFamily": "monospace", "fontSize": "13px", "padding": "6px"},
            style_header={"fontWeight": "700", "background": "#f8fafc"},
        ),
    ])
    prows = queries.quality_by_prompt(db_path, app_id, hours, project)
    prompt_table = html.Div(style={"marginTop": "12px", "background": "white", "borderRadius": "10px", "padding": "10px"}, children=[
        html.Div("LLM-judge quality by prompt version", style={"fontWeight": 600, "marginBottom": "6px"}),
        dash_table.DataTable(
            data=prows or [{"prompt_id": "(no judge scores yet)"}],
            columns=[{"name": c, "id": c} for c in
                     ["prompt_id", "relevance", "coherence", "safety", "graded"]],
            style_cell={"fontFamily": "monospace", "fontSize": "12px", "padding": "6px",
                        "maxWidth": "320px", "overflow": "hidden", "textOverflow": "ellipsis"},
            style_header={"fontWeight": "700", "background": "#f8fafc"},
        ),
    ])
    return html.Div([judge_cards, note, name_table, prompt_table])


def _traces_body(db_path, app_id, hours, selected, show_cost=False, project=None,
                 show_waterfall=True):
    traces = queries.recent_traces(db_path, app_id, hours, limit=200, project=project)
    cols = ["started_at", "project_id", "app_id", "name", "spans", "tokens", "status", "trace_id"]
    if show_cost:
        cols.insert(5, "cost")
    table = dash_table.DataTable(
        id="traces-table",
        data=traces,
        columns=[{"name": c, "id": c} for c in cols],
        page_size=12, sort_action="native", filter_action="native",
        style_cell={"fontFamily": "monospace", "fontSize": "12px", "padding": "6px",
                    "maxWidth": "220px", "overflow": "hidden", "textOverflow": "ellipsis"},
        style_header={"fontWeight": "700", "background": "#f8fafc"},
        style_data_conditional=[{"if": {"filter_query": "{status} = error"},
                                 "backgroundColor": "#fef2f2"}],
        cell_selectable=True,
    )
    detail = []
    if selected:
        spans = queries.trace_spans(db_path, selected)
        span_cols = ["type", "name", "model", "duration_ms", "total_tokens", "status"]
        if show_cost:
            span_cols.insert(5, "cost_usd")
        detail = [
            html.Div(f"Trace {selected[:12]}…  ·  {len(spans)} spans",
                     style={"fontWeight": 600, "margin": "14px 0 6px"}),
            *([dcc.Graph(figure=build_waterfall(spans))] if show_waterfall else []),
            dash_table.DataTable(
                data=[{k: s.get(k) for k in span_cols} for s in spans],
                columns=[{"name": c, "id": c} for c in span_cols],
                style_cell={"fontFamily": "monospace", "fontSize": "12px", "padding": "6px"},
                style_header={"fontWeight": "700", "background": "#f8fafc"},
            ),
            html.Div("Prompts & responses", style={"fontWeight": 600, "margin": "16px 0 6px"}),
            html.Div(build_messages(spans)),
        ]
    return html.Div([
        html.Div(style={"background": "white", "borderRadius": "10px", "padding": "10px"}, children=[
            html.Div("Recent traces — click a row to open the trace detail",
                     style={"fontWeight": 600, "marginBottom": "6px"}),
            table,
        ]),
        html.Div(detail, style={"background": "white", "borderRadius": "10px",
                                "padding": "10px", "marginTop": "12px"} if selected else {}),
    ])


def _prompts_body(repo: PromptRepo):
    apps = repo.list_apps()
    if not apps:
        return html.Div(f"No prompts found under {repo.root}. "
                        "Launch with --prompts-dir <path> (or set PRISM_PROMPTS_DIR).",
                        style={"color": "#94a3b8", "padding": "12px"})
    dd = lambda i, w: dict(id=i, clearable=False, style={"width": w})
    return html.Div([
        html.Div(style={"display": "flex", "gap": "10px", "alignItems": "center",
                        "background": "white", "borderRadius": "10px", "padding": "10px"}, children=[
            html.Span("Application", style={"fontSize": "12px", "color": "#64748b"}),
            dcc.Dropdown(options=[{"label": a, "value": a} for a in apps], value=apps[0], **dd("pr-app", "200px")),
            html.Span("Prompt", style={"fontSize": "12px", "color": "#64748b"}),
            dcc.Dropdown(**dd("pr-name", "240px")),
            html.Span("Version", style={"fontSize": "12px", "color": "#64748b"}),
            dcc.Dropdown(**dd("pr-version", "110px")),
        ]),
        html.Div(id="pr-detail", style={"marginTop": "12px"}),
    ])


def _prompt_detail(repo: PromptRepo, db_path: str, app: str, name: str, version: int):
    p = repo.load(app, name, version)
    usage = queries.prompt_usage(db_path, p.ref)
    meta_bits = " · ".join(f"{k}: {v}" for k, v in p.meta.items() if k != "version")

    # usage overlay across all versions, so v1 vs v2 is comparable
    rows = []
    for v in repo.versions(app, name):
        u = queries.prompt_usage(db_path, f"{app}/{name}@v{v}")
        rows.append({"version": f"v{v}", "calls": u["calls"], "tokens": u["tokens"],
                     "avg_ms": u["avg_ms"], "errors": u["errors"]})

    # diff vs previous version
    diff_block = []
    vers = repo.versions(app, name)
    if version in vers and vers.index(version) > 0:
        prev = vers[vers.index(version) - 1]
        before = repo.load(app, name, prev).template.splitlines()
        after = p.template.splitlines()
        diff = list(difflib.unified_diff(before, after, fromfile=f"v{prev}", tofile=f"v{version}", lineterm=""))
        diff_block = [html.Div(f"Diff v{prev} → v{version}", style={"fontWeight": 600, "margin": "14px 0 4px"}),
                      _diff_pre(diff)]

    return html.Div([
        html.Div([html.Span(p.ref, style={"fontWeight": 700, "fontSize": "15px"}),
                  html.Span(f"   {meta_bits}", style={"color": "#64748b", "fontSize": "12px"})]),
        html.Div(style={"display": "flex", "gap": "12px", "marginTop": "10px", "flexWrap": "wrap"}, children=[
            html.Div(style={"flex": "2", "minWidth": "420px"}, children=[
                html.Div("Template", style={"fontSize": "11px", "color": "#64748b"}),
                _pre(p.template, "#f8fafc"),
                *diff_block,
            ]),
            html.Div(style={"flex": "1", "minWidth": "300px"}, children=[
                html.Div("This version — usage (all time)", style={"fontSize": "11px", "color": "#64748b"}),
                html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "marginBottom": "10px"}, children=[
                    _card("Calls", f"{usage['calls']:,}"),
                    _card("Tokens", f"{int(usage['tokens']):,}"),
                    _card("Avg ms", f"{usage['avg_ms']:.0f}"),
                ]),
                html.Div("All versions", style={"fontSize": "11px", "color": "#64748b"}),
                dash_table.DataTable(
                    data=rows, columns=[{"name": c, "id": c} for c in ["version", "calls", "tokens", "avg_ms", "errors"]],
                    style_cell={"fontFamily": "monospace", "fontSize": "12px", "padding": "6px"},
                    style_header={"fontWeight": "700", "background": "#f8fafc"},
                ),
            ]),
        ]),
    ])


def _diff_pre(diff_lines: list[str]) -> html.Pre:
    if not diff_lines:
        return html.Pre("(no changes)", style={"color": "#94a3b8"})
    spans = []
    for ln in diff_lines:
        color = "#16a34a" if ln.startswith("+") else "#dc2626" if ln.startswith("-") else "#475569"
        spans.append(html.Span(ln + "\n", style={"color": color}))
    return html.Pre(spans, style={"whiteSpace": "pre-wrap", "wordBreak": "break-word",
                                  "padding": "8px 10px", "background": "#f8fafc", "borderRadius": "6px",
                                  "fontSize": "12px", "maxHeight": "260px", "overflow": "auto"})


def run(db_path: Optional[str] = None, host: str = "127.0.0.1", port: int = 8052,
        debug: bool = False, show_cost: bool = False, prompts_root: Optional[str] = None,
        show_waterfall: Optional[bool] = None, show_quality: Optional[bool] = None) -> None:
    create_app(db_path, show_cost=show_cost, prompts_root=prompts_root,
               show_waterfall=show_waterfall, show_quality=show_quality).run(
        host=host, port=port, debug=debug)
