"""Wire/record models shared by the SDK, transport, collector, and store.

Plain dataclasses (no pydantic dependency in the SDK core — products only pull in
``httpx``). The collector validates loosely and normalizes by ``schema_version``.

Time convention (decision B5): all timestamps are UTC ISO-8601 strings. Durations
are measured locally on the producing host via a monotonic clock and stored as
``duration_ms`` — never derived by subtracting cross-host timestamps.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Optional

from .version import SCHEMA_VERSION

# Span kinds — must match ARCHITECTURE.md spans.type enum.
SPAN_KINDS = ("llm", "tool", "retrieval", "chain", "agent", "span")


def _clean(d: dict) -> dict:
    """Drop None values so payloads stay compact."""
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class Span:
    span_id: str
    trace_id: str
    name: str
    type: str = "span"  # one of SPAN_KINDS
    parent_span_id: Optional[str] = None

    # LLM-specific (None for non-llm spans)
    model: Optional[str] = None
    prompt_id: Optional[str] = None
    params: Optional[dict] = None
    system_prompt: Optional[str] = None
    user_message: Optional[str] = None
    response_text: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    thoughts_tokens: Optional[int] = None
    tokens_source: Optional[str] = None  # "model" | "estimated"
    finish_reason: Optional[str] = None
    full_gemini_response: Optional[str] = None
    cost_usd: Optional[float] = None
    response_id: Optional[str] = None
    # Audit/reproducibility: SHA-256 of the full input/output (before truncation).
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None

    # Generic span fields
    input: Optional[Any] = None
    output: Optional[Any] = None
    attributes: dict = field(default_factory=dict)
    status: str = "ok"  # "ok" | "error"
    error: Optional[str] = None

    # Identity / governance (stamped from config)
    app_id: Optional[str] = None
    env: Optional[str] = None
    app_type: Optional[str] = None
    data_classification: Optional[str] = None
    internal: Optional[str] = None  # e.g. "eval" — excluded from product metrics

    # Time (UTC ISO strings) + locally measured duration
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    created_at: Optional[str] = None   # set on emit; falls back to started_at
    duration_ms: Optional[float] = None

    schema_version: int = SCHEMA_VERSION

    def to_wire(self) -> dict:
        return _clean(dataclasses.asdict(self))


@dataclass
class Score:
    """An eval result attached to a span (or trace). Written via POST /v1/scores."""
    name: str
    value: Optional[float] = None
    label: Optional[str] = None
    span_id: Optional[str] = None
    trace_id: Optional[str] = None
    source: str = "heuristic"  # "heuristic" | "llm_judge" | "human"
    rationale: Optional[str] = None
    created_at: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def to_wire(self) -> dict:
        return _clean(dataclasses.asdict(self))


@dataclass
class IngestBatch:
    """The envelope POSTed to /v1/ingest."""
    spans: list[dict]
    schema_version: int = SCHEMA_VERSION

    def to_wire(self) -> dict:
        return {"schema_version": self.schema_version, "spans": self.spans}
