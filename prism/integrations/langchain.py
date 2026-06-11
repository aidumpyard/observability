"""PrismCallbackHandler — LangChain & LangGraph auto-instrumentation (SDK Layer 3).

Pass it via ``config={"callbacks": [PrismCallbackHandler()]}`` to any
``invoke``/``stream`` call. It turns chain/tool/LLM callback events into Prism
spans, nesting them correctly using LangChain's ``run_id`` / ``parent_run_id`` tree
(authoritative — independent of thread/context quirks). It also keeps the Prism
``contextvar`` pointed at the most-recent open span, so *raw* gateway calls made
inside a graph node (e.g. via a non-LangChain HTTP client) still nest under that
node.

Safety: every hook is wrapped so a capture failure is swallowed (N1). If Prism is
not initialized, all hooks are no-ops.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from langchain_core.callbacks import BaseCallbackHandler
except Exception:  # pragma: no cover - integration only used where langchain exists
    BaseCallbackHandler = object  # type: ignore

from .. import config, context
from ..cost import compute_cost
from ..models import Span
from ..safety import safe_call
from ..tracing import _emit, _truncate


def _model_name(serialized, kwargs) -> Optional[str]:
    inv = kwargs.get("invocation_params") or {}
    for key in ("model", "model_name", "model_id"):
        if inv.get(key):
            return inv[key]
    if isinstance(serialized, dict):
        if serialized.get("name"):
            return serialized["name"]
        ident = serialized.get("id")
        if isinstance(ident, list) and ident:
            return ident[-1]
    return None


def _usage_from_response(response) -> dict:
    """Pull token usage out of an LLMResult across langchain versions."""
    out = {}
    llm_output = getattr(response, "llm_output", None) or {}
    tu = llm_output.get("token_usage") or llm_output.get("usage") or {}
    out["prompt_tokens"] = tu.get("prompt_tokens") or tu.get("input_tokens")
    out["completion_tokens"] = tu.get("completion_tokens") or tu.get("output_tokens")
    out["total_tokens"] = tu.get("total_tokens")
    # newer: usage_metadata on the message
    try:
        gen = response.generations[0][0]
        text = getattr(gen, "text", None)
        msg = getattr(gen, "message", None)
        um = getattr(msg, "usage_metadata", None) if msg else None
        if um:
            out["prompt_tokens"] = out["prompt_tokens"] or um.get("input_tokens")
            out["completion_tokens"] = out["completion_tokens"] or um.get("output_tokens")
            out["total_tokens"] = out["total_tokens"] or um.get("total_tokens")
        if text:
            out["response_text"] = text
    except Exception:  # noqa: BLE001
        pass
    return out


class PrismCallbackHandler(BaseCallbackHandler):
    def __init__(self):
        # run_id -> {"span": Span, "start": float, "token": contextvar token}
        self._runs: dict = {}

    # ---- lifecycle helpers ------------------------------------------------
    def _start(self, run_id, parent_run_id, name: str, kind: str, **fields) -> None:
        if not config.is_enabled():
            return
        tr = context.current_trace()
        if tr is None:
            tr = context.TraceCtx(trace_id=context.new_trace_id(), name=name)
            context.set_trace(tr)  # bound to handler lifetime (use prism.trace() to scope)

        parent = self._runs.get(parent_run_id)
        if parent is not None:
            parent_span_id = parent["span"].span_id
        else:
            cur = context.current_span()
            parent_span_id = cur.span_id if cur else None

        sp = Span(span_id=context.new_span_id(), trace_id=tr.trace_id, name=name,
                  type=kind, parent_span_id=parent_span_id, started_at=context.now_iso())
        for k, v in fields.items():
            setattr(sp, k, v)
        token = context.set_span(context.SpanCtx(sp.span_id, sp.trace_id, parent_span_id))
        self._runs[str(run_id)] = {"span": sp, "start": context.monotonic_ms(), "token": token}

    def _end(self, run_id, **fields) -> None:
        rec = self._runs.pop(str(run_id), None)
        if not rec:
            return
        sp: Span = rec["span"]
        for k, v in fields.items():
            if v is not None:
                setattr(sp, k, v)
        sp.ended_at = context.now_iso()
        sp.duration_ms = round(context.monotonic_ms() - rec["start"], 3)
        safe_call(context.reset_span, rec["token"])
        safe_call(_emit, sp)

    # ---- chains / graph nodes --------------------------------------------
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kw):
        name = kw.get("name") or (serialized or {}).get("name") or "chain"
        safe_call(self._start, run_id, parent_run_id, name, "chain", input=_truncate(inputs))

    def on_chain_end(self, outputs, *, run_id, **kw):
        safe_call(self._end, run_id, output=_truncate(outputs), status="ok")

    def on_chain_error(self, error, *, run_id, **kw):
        safe_call(self._end, run_id, status="error", error=str(error))

    # ---- tools ------------------------------------------------------------
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kw):
        name = kw.get("name") or (serialized or {}).get("name") or "tool"
        safe_call(self._start, run_id, parent_run_id, name, "tool", input=_truncate(input_str))

    def on_tool_end(self, output, *, run_id, **kw):
        safe_call(self._end, run_id, output=_truncate(output), status="ok")

    def on_tool_error(self, error, *, run_id, **kw):
        safe_call(self._end, run_id, status="error", error=str(error))

    # ---- LLMs -------------------------------------------------------------
    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kw):
        model = _model_name(serialized, kw)
        first = prompts[0] if prompts else None
        safe_call(self._start, run_id, parent_run_id, model or "llm", "llm",
                  model=model, user_message=_truncate(first))

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kw):
        model = _model_name(serialized, kw)
        flat = messages[0] if messages else []
        text = "\n".join(getattr(m, "content", str(m)) for m in flat) if flat else None
        safe_call(self._start, run_id, parent_run_id, model or "chat", "llm",
                  model=model, user_message=_truncate(text))

    def on_llm_end(self, response, *, run_id, **kw):
        usage = safe_call(_usage_from_response, response, default={}) or {}
        rec = self._runs.get(str(run_id))
        model = rec["span"].model if rec else None
        cfg = config.get_config()
        cost = safe_call(compute_cost, model, usage.get("prompt_tokens"),
                         usage.get("completion_tokens")) if (cfg and cfg.track_cost) else None
        safe_call(self._end, run_id, status="ok", tokens_source="model",
                  response_text=_truncate(usage.get("response_text")),
                  prompt_tokens=usage.get("prompt_tokens"),
                  completion_tokens=usage.get("completion_tokens"),
                  total_tokens=usage.get("total_tokens"), cost_usd=cost)

    def on_llm_error(self, error, *, run_id, **kw):
        safe_call(self._end, run_id, status="error", error=str(error))
