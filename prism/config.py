"""Global SDK configuration and lifecycle.

``prism.init()`` populates a process-global ``Config``. Until it is called — or if
it is torn down — the SDK is *disabled* and every public entry point is a no-op
(guarantee N1/N2). Config is read-mostly after init.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

DEFAULT_MAX_TEXT_CHARS = 8000
DEFAULT_QUEUE_MAX = 10_000
DEFAULT_FLUSH_INTERVAL = 1.0  # seconds
DEFAULT_BATCH_SIZE = 100


@dataclass
class Config:
    app: str
    endpoint: str                       # gateway base URL, e.g. http://host/api/llm/process
    collector_url: str                  # Prism collector base, e.g. https://host:9100
    api_key: Optional[str] = None       # gateway key
    ingest_key: Optional[str] = None    # per-app key sent as X-Prism-Key
    env: str = "dev"
    app_type: Optional[str] = None
    data_classification: str = "Public"

    # Capture behavior
    sample_rate: float = 1.0
    capture_io: bool = True
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS
    redact: Optional[Callable[[str], str]] = None
    # Cost is opt-in: by default Prism tracks tokens only (the gateway bills in
    # tokens, not dollars). Set track_cost=True to also compute cost_usd from the
    # price table.
    track_cost: bool = False

    # Transport
    verify: object = True               # httpx verify: True | False | path-to-cert
    queue_max: int = DEFAULT_QUEUE_MAX
    flush_interval: float = DEFAULT_FLUSH_INTERVAL
    batch_size: int = DEFAULT_BATCH_SIZE
    timeout: float = 10.0

    enabled: bool = True

    # Counters for self-observability (B-review item: surface dropped spans)
    _dropped: int = field(default=0)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def incr_dropped(self, n: int = 1) -> None:
        with self._lock:
            self._dropped += n

    @property
    def dropped(self) -> int:
        return self._dropped


_config: Optional[Config] = None
_transport = None  # set by transport.start(); type: SpanTransport


def set_config(cfg: Optional[Config]) -> None:
    global _config
    _config = cfg


def get_config() -> Optional[Config]:
    return _config


def is_enabled() -> bool:
    return _config is not None and _config.enabled


def set_transport(t) -> None:
    global _transport
    _transport = t


def get_transport():
    return _transport
