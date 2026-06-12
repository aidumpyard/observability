"""Layer-1 tracing primitives: trace(), observe(), span().

Each works as both a decorator (sync or async fn) and a context manager. They open
context, time the body with a monotonic clock (local duration_ms — decision B5),
capture status/errors, and emit a finished span to the transport on exit. All
emission is wrapped so it can never break the product (N1).
"""

from __future__ import annotations

import functools
import inspect
import random
from typing import Any, Optional

from . import config, context
from .models import SPAN_KINDS, Span
from .safety import safe_call


def _sampled() -> bool:
    cfg = config.get_config()
    if cfg is None:
        return False
    return cfg.sample_rate >= 1.0 or random.random() < cfg.sample_rate


def _truncate(val: Any) -> Any:
    cfg = config.get_config()
    if cfg is None or val is None:
        return val
    if not cfg.capture_io:
        return None
    text = val if isinstance(val, str) else repr(val)
    if cfg.redact:
        text = safe_call(cfg.redact, text, default=text)
    if len(text) > cfg.max_text_chars:
        text = text[: cfg.max_text_chars] + "…[truncated]"
    return text


def _emit(span: Span) -> None:
    transport = config.get_transport()
    cfg = config.get_config()
    if transport is None or cfg is None:
        return
    span.app_id = span.app_id or cfg.app
    span.env = span.env or cfg.env
    span.app_type = span.app_type or cfg.app_type
    span.data_classification = span.data_classification or cfg.data_classification
    tr = context.current_trace()
    if tr is not None:                          # carry end-user identity onto spans
        span.user_id = span.user_id or tr.user_id
        span.session_id = span.session_id or tr.session_id
    span.created_at = span.created_at or span.started_at or context.now_iso()
    transport.enqueue(span.to_wire())


class _SpanHandle:
    """Returned by `with prism.span(...)`. Lets product code attach IO/attrs."""

    def __init__(self, span: Span):
        self._span = span

    def input(self, value: Any) -> "_SpanHandle":
        self._span.input = _truncate(value)
        return self

    def output(self, value: Any) -> "_SpanHandle":
        self._span.output = _truncate(value)
        return self

    def attr(self, **kwargs) -> "_SpanHandle":
        self._span.attributes.update(kwargs)
        return self

    def set_error(self, err: str) -> "_SpanHandle":
        self._span.status = "error"
        self._span.error = err
        return self


class _Tracer:
    """Backs both trace() and span()/observe(): a dual context-manager/decorator."""

    def __init__(self, name: str, kind: str = "span", *, is_trace: bool = False,
                 user_id: Optional[str] = None, session_id: Optional[str] = None,
                 metadata: Optional[dict] = None, span_obj: Optional[Span] = None):
        self.name = name
        self.kind = kind if kind in SPAN_KINDS else "span"
        self.is_trace = is_trace
        self.user_id = user_id
        self.session_id = session_id
        self.metadata = metadata or {}
        self._span = span_obj
        self._tokens: list = []
        self._start_ms = 0.0

    # -- context manager --
    def __enter__(self):
        if not config.is_enabled():
            return _SpanHandle(Span(span_id="noop", trace_id="noop", name=self.name))

        trace_ctx = context.current_trace()
        if trace_ctx is None:
            sampled = _sampled()
            trace_ctx = context.TraceCtx(
                trace_id=context.new_trace_id(), name=self.name, sampled=sampled,
                user_id=self.user_id, session_id=self.session_id, metadata=self.metadata,
            )
            self._tokens.append(("trace", context.set_trace(trace_ctx)))

        parent = context.current_span()
        sp = self._span or Span(span_id=context.new_span_id(), trace_id=trace_ctx.trace_id, name=self.name)
        sp.span_id = sp.span_id or context.new_span_id()
        sp.trace_id = trace_ctx.trace_id
        sp.type = self.kind
        sp.parent_span_id = parent.span_id if parent else None
        sp.started_at = context.now_iso()
        self._span = sp
        self._start_ms = context.monotonic_ms()
        self._tokens.append(("span", context.set_span(
            context.SpanCtx(span_id=sp.span_id, trace_id=sp.trace_id, parent_span_id=sp.parent_span_id)
        )))
        return _SpanHandle(sp)

    def __exit__(self, exc_type, exc, tb):
        if not config.is_enabled() or self._span is None:
            self._reset()
            return False
        sp = self._span
        sp.ended_at = context.now_iso()
        sp.duration_ms = round(context.monotonic_ms() - self._start_ms, 3)
        if exc_type is not None:
            sp.status = "error"
            sp.error = f"{exc_type.__name__}: {exc}"
        safe_call(_emit, sp)
        self._reset()
        return False  # never suppress product exceptions

    def _reset(self) -> None:
        for kind, token in reversed(self._tokens):
            try:
                (context.reset_span if kind == "span" else context.reset_trace)(token)
            except Exception:  # noqa: BLE001
                pass
        self._tokens = []

    # -- decorator --
    def __call__(self, fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                with _Tracer(self.name or fn.__name__, self.kind, is_trace=self.is_trace,
                             user_id=self.user_id, session_id=self.session_id,
                             metadata=self.metadata) as h:
                    h.input({"args": args, "kwargs": kwargs})
                    out = await fn(*args, **kwargs)
                    h.output(out)
                    return out
            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with _Tracer(self.name or fn.__name__, self.kind, is_trace=self.is_trace,
                         user_id=self.user_id, session_id=self.session_id,
                         metadata=self.metadata) as h:
                h.input({"args": args, "kwargs": kwargs})
                out = fn(*args, **kwargs)
                h.output(out)
                return out
        return wrapper


def trace(name: Optional[str] = None, *, user_id: Optional[str] = None,
          session_id: Optional[str] = None, metadata: Optional[dict] = None):
    """Open a product-level trace. Use as decorator or `with prism.trace(...)`."""
    return _Tracer(name or "trace", "chain", is_trace=True,
                   user_id=user_id, session_id=session_id, metadata=metadata)


def span(name: str, *, kind: str = "span"):
    """Open a span under the current trace. Decorator or context manager."""
    return _Tracer(name, kind)


def observe(*, name: Optional[str] = None, kind: str = "span"):
    """Decorator: wrap any function as a span."""
    def deco(fn):
        return _Tracer(name or fn.__name__, kind)(fn)
    return deco
