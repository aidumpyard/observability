"""Prism SDK — public API.

Typical product usage::

    import prism
    prism.init(app="claims-agent",
               endpoint="https://gw/api/llm/process",
               collector_url="https://prism-host:9100",
               ingest_key="…")

    with prism.trace("checkout", user_id="u1"):
        resp = prism.llm.generate(message="hi", model="gemini-2.5-flash")

Every entry point is a no-op until ``init`` is called, and never raises into product
code (N1) or blocks the request path (N2).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from . import config, context
from .client import capture_llm, llm
from .config import Config
from .safety import safe_call
from .tracing import observe, span, trace
from .transport import start_transport
from .version import SCHEMA_VERSION, __version__

__all__ = [
    "init", "shutdown", "trace", "span", "observe", "llm", "capture_llm",
    "inject", "extract", "continue_trace", "pii_redactor", "dropped",
    "__version__", "SCHEMA_VERSION",
]


def init(
    app: str,
    *,
    endpoint: str,
    collector_url: str,
    api_key: Optional[str] = None,
    ingest_key: Optional[str] = None,
    env: str = "dev",
    app_type: Optional[str] = None,
    data_classification: str = "Public",
    sample_rate: float = 1.0,
    capture_io: bool = True,
    max_text_chars: int = 8000,
    redact: Optional[Callable[[str], str]] = None,
    verify=True,
    track_cost: bool = False,
    cost_table: Optional[dict] = None,
) -> None:
    """Configure Prism for this process and start the background transport."""
    cfg = Config(
        app=app, endpoint=endpoint, collector_url=collector_url,
        api_key=api_key, ingest_key=ingest_key, env=env, app_type=app_type,
        data_classification=data_classification, sample_rate=sample_rate,
        capture_io=capture_io, max_text_chars=max_text_chars, redact=redact, verify=verify,
        track_cost=track_cost,
    )
    config.set_config(cfg)
    config.set_transport(start_transport(cfg))
    if cost_table:
        from . import cost
        cost.DEFAULT_PRICES.update(cost_table)


def shutdown(timeout: float = 3.0) -> None:
    t = config.get_transport()
    if t is not None:
        safe_call(t.flush, timeout)
        safe_call(t.shutdown, timeout)
    config.set_transport(None)
    config.set_config(None)


def dropped() -> int:
    """Self-observability: spans dropped due to queue overflow / collector down."""
    cfg = config.get_config()
    return cfg.dropped if cfg else 0


# --- W3C trace-context propagation (Layer 4) -------------------------------

def inject(headers: dict) -> dict:
    """Stamp the active trace into outbound headers as `traceparent`."""
    tr = context.current_trace()
    sp = context.current_span()
    if tr is not None:
        span_id = sp.span_id if sp else context.new_span_id()
        headers["traceparent"] = context.format_traceparent(tr.trace_id, span_id, tr.sampled)
    return headers


def extract(headers) -> Optional[tuple]:
    tp = headers.get("traceparent") if hasattr(headers, "get") else None
    return context.parse_traceparent(tp) if tp else None


class continue_trace:
    """Continue a trace started upstream (frontend/another service).

    Usage::
        with prism.continue_trace(headers=request.headers, name="POST /chat"):
            ...
    """

    def __init__(self, headers=None, name: str = "request",
                 user_id: Optional[str] = None, session_id: Optional[str] = None):
        self.name = name
        self.user_id = user_id
        self.session_id = session_id
        parsed = extract(headers) if headers is not None else None
        self.trace_id = parsed[0] if parsed else context.new_trace_id()
        self.parent_span_id = parsed[1] if parsed else None
        self.sampled = parsed[2] if parsed else True
        self._token = None

    def __enter__(self):
        if not config.is_enabled():
            return self
        ctx = context.TraceCtx(
            trace_id=self.trace_id, name=self.name, sampled=self.sampled,
            user_id=self.user_id, session_id=self.session_id,
        )
        self._token = context.set_trace(ctx)
        if self.parent_span_id:
            context.set_span(context.SpanCtx(span_id=self.parent_span_id, trace_id=self.trace_id))
        return self

    def __exit__(self, *exc):
        if self._token is not None:
            safe_call(context.reset_trace, self._token)
        return False


# --- a tiny default PII redactor (opt-in via init(redact=...)) -------------

_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[card]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
]


def pii_redactor(text: str) -> str:
    for pat, repl in _PII:
        text = pat.sub(repl, text)
    return text
