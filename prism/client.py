"""The force-full LLM client (ARCHITECTURE §2).

``prism.llm.generate(...)`` calls the gateway but *always* sets
``full_gemini_response="true"`` so it can harvest real token usage / modelVersion /
finishReason, records an ``llm`` span, then returns to the caller whatever shape
they originally asked for (bare text or full envelope). Works identically against
the real gateway and the simulator.

If the gateway can't be reached, the error is raised to the product (it's the
product's own call) — but the span is still emitted with status=error so the
failure is observable.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from . import config, context
from .cost import compute_cost
from .models import Span
from .safety import safe_call
from .tracing import _emit, _truncate


def _wants_full(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() == "true"


def _extract_usage(envelope: dict) -> dict:
    """Pull real metrics out of the Gemini envelope. tokens_source='model'."""
    um = envelope.get("usageMetadata") or {}
    cand = (envelope.get("candidates") or [{}])[0]
    text = ""
    parts = (cand.get("content") or {}).get("parts") or []
    if parts:
        text = parts[0].get("text", "")
    return {
        "response_text": text,
        "prompt_tokens": um.get("promptTokenCount"),
        "completion_tokens": um.get("candidatesTokenCount"),
        "total_tokens": um.get("totalTokenCount"),
        "thoughts_tokens": um.get("thoughtsTokenCount"),
        "finish_reason": cand.get("finishReason"),
        "model": envelope.get("modelVersion"),
        "response_id": envelope.get("responseId"),
        "tokens_source": "model",
    }


def _shape_for_caller(envelope: dict, wants_full: bool):
    if wants_full:
        return envelope
    cand = (envelope.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or [{}]
    return parts[0].get("text", "")


class _LLM:
    def generate(
        self,
        message: str,
        *,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        params: Optional[dict] = None,
        full_gemini_response: Any = None,   # what the CALLER wants back
        prompt_id: Optional[str] = None,
        **extra,
    ):
        cfg = config.get_config()
        if cfg is None:
            raise RuntimeError("prism.init() must be called before prism.llm.generate()")

        caller_wants_full = _wants_full(full_gemini_response)

        # Build the gateway request — but force full so we always get usage.
        body = {
            "message": message,
            "system_prompt": system_prompt,
            "model": model,
            "apiKey": cfg.api_key,
            "data_classification": cfg.data_classification,
            "full_gemini_response": "true",   # the force-full trick
            "params": params or {},
            **extra,
        }
        body = {k: v for k, v in body.items() if v is not None}

        # Open an llm span around the call.
        from .tracing import _Tracer  # local import avoids cycle at module load
        tracer = _Tracer(name=model or "llm", kind="llm")
        handle = tracer.__enter__()
        sp: Span = handle._span
        sp.model = model
        sp.params = params
        sp.prompt_id = prompt_id
        sp.system_prompt = _truncate(system_prompt)
        sp.user_message = _truncate(message)
        sp.full_gemini_response = str(full_gemini_response)

        try:
            resp = httpx.post(cfg.endpoint, json=body, timeout=cfg.timeout, verify=cfg.verify)
            resp.raise_for_status()
            envelope = resp.json()
        except Exception as exc:  # product's own call — record then re-raise
            tracer.__exit__(type(exc), exc, exc.__traceback__)
            raise

        usage = safe_call(_extract_usage, envelope, default={}) or {}
        sp.response_text = _truncate(usage.get("response_text"))
        sp.prompt_tokens = usage.get("prompt_tokens")
        sp.completion_tokens = usage.get("completion_tokens")
        sp.total_tokens = usage.get("total_tokens")
        sp.thoughts_tokens = usage.get("thoughts_tokens")
        sp.finish_reason = usage.get("finish_reason")
        sp.response_id = usage.get("response_id")
        sp.tokens_source = usage.get("tokens_source", "model")
        sp.model = usage.get("model") or model  # prefer reported modelVersion
        if cfg.track_cost:
            sp.cost_usd = safe_call(
                compute_cost, sp.model, sp.prompt_tokens, sp.completion_tokens, default=None
            )

        tracer.__exit__(None, None, None)
        return _shape_for_caller(envelope, caller_wants_full)


llm = _LLM()


def capture_llm(call, *, request: Optional[dict] = None, model: Optional[str] = None,
                prompt_id: Optional[str] = None):
    """Wrap an existing raw call (lambda returning an httpx.Response or dict).

    For products already issuing their own gateway POST. Records an llm span with
    whatever metrics the response exposes; tokens marked 'estimated' if absent.
    ``prompt_id`` (e.g. 'loan_agent/extract@v1') links the span to a prompt version.
    """
    cfg = config.get_config()
    if cfg is None:
        return call()

    from .tracing import _Tracer
    tracer = _Tracer(name=model or "llm", kind="llm")
    handle = tracer.__enter__()
    sp: Span = handle._span
    sp.model = model
    sp.prompt_id = prompt_id
    if request:
        sp.user_message = _truncate(request.get("message"))
        sp.system_prompt = _truncate(request.get("system_prompt"))
        sp.params = request.get("params")

    try:
        result = call()
    except Exception as exc:
        tracer.__exit__(type(exc), exc, exc.__traceback__)
        raise

    envelope = result.json() if isinstance(result, httpx.Response) else result
    if isinstance(envelope, dict):
        usage = safe_call(_extract_usage, envelope, default={}) or {}
        sp.response_text = _truncate(usage.get("response_text"))
        sp.prompt_tokens = usage.get("prompt_tokens")
        sp.completion_tokens = usage.get("completion_tokens")
        sp.total_tokens = usage.get("total_tokens")
        sp.finish_reason = usage.get("finish_reason")
        sp.model = usage.get("model") or model
        sp.tokens_source = usage.get("tokens_source", "model")
        if cfg.track_cost:
            sp.cost_usd = safe_call(compute_cost, sp.model, sp.prompt_tokens, sp.completion_tokens)
    else:  # bare string — only text available, tokens unknown
        sp.response_text = _truncate(str(envelope))
        sp.tokens_source = "estimated"

    tracer.__exit__(None, None, None)
    return result
