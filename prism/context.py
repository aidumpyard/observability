"""Trace/span context propagation and ID generation.

Uses ``contextvars`` so the active trace and span follow execution across ``await``
boundaries and into thread-pool executors (guarantee: no locking on the product
hot path). IDs follow the W3C trace-context shape so they double as ``traceparent``
fields for cross-process / button-to-end tracing.
"""

from __future__ import annotations

import contextvars
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# --- ID helpers (W3C trace-context compatible) -----------------------------

def new_trace_id() -> str:
    """16-byte / 32-hex trace id (globally unique across distributed producers)."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """8-byte / 16-hex span id."""
    return secrets.token_hex(8)


def now_iso() -> str:
    """UTC ISO-8601 (decision B5: everything stored in UTC)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


def format_traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"


def parse_traceparent(value: str) -> Optional[tuple[str, str, bool]]:
    """Return (trace_id, parent_span_id, sampled) or None if unparseable."""
    if not value:
        return None
    parts = value.strip().split("-")
    if len(parts) != 4:
        return None
    _, trace_id, parent_id, flags = parts
    if len(trace_id) != 32 or len(parent_id) != 16:
        return None
    return trace_id, parent_id, bool(int(flags, 16) & 0x01)


# --- Active context ---------------------------------------------------------

@dataclass
class TraceCtx:
    trace_id: str
    name: str
    sampled: bool = True
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class SpanCtx:
    span_id: str
    trace_id: str
    parent_span_id: Optional[str] = None


_current_trace: contextvars.ContextVar[Optional[TraceCtx]] = contextvars.ContextVar(
    "prism_trace", default=None
)
_current_span: contextvars.ContextVar[Optional[SpanCtx]] = contextvars.ContextVar(
    "prism_span", default=None
)


def current_trace() -> Optional[TraceCtx]:
    return _current_trace.get()


def current_span() -> Optional[SpanCtx]:
    return _current_span.get()


def set_trace(ctx: Optional[TraceCtx]):
    return _current_trace.set(ctx)


def reset_trace(token) -> None:
    _current_trace.reset(token)


def set_span(ctx: Optional[SpanCtx]):
    return _current_span.set(ctx)


def reset_span(token) -> None:
    _current_span.reset(token)
