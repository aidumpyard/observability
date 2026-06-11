"""N2 guarantee: capture never blocks the product.

The hot path only enqueues a finished span dict onto a bounded queue. A single
background daemon thread drains the queue, batches spans, and ships them to the
collector over HTTPS. If the queue is full we *drop* (and count) rather than block
the producer. If the collector is down, batches are retried briefly then dropped —
the product is never affected.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

import httpx

from .config import Config
from .models import IngestBatch

log = logging.getLogger("prism")


class SpanTransport:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.q: queue.Queue[dict] = queue.Queue(maxsize=cfg.queue_max)
        self._stop = threading.Event()
        self._client = httpx.Client(timeout=cfg.timeout, verify=cfg.verify)
        self._thread = threading.Thread(target=self._run, name="prism-transport", daemon=True)

    def start(self) -> "SpanTransport":
        self._thread.start()
        return self

    # --- producer side (hot path) ------------------------------------------
    def enqueue(self, span_wire: dict) -> None:
        """Non-blocking. Drops + counts on overflow."""
        try:
            self.q.put_nowait(span_wire)
        except queue.Full:
            self.cfg.incr_dropped(1)

    # --- consumer side (background thread) ---------------------------------
    def _run(self) -> None:
        batch: list[dict] = []
        last_flush = time.monotonic()
        while not self._stop.is_set():
            timeout = max(0.0, self.cfg.flush_interval - (time.monotonic() - last_flush))
            try:
                item = self.q.get(timeout=timeout)
                batch.append(item)
            except queue.Empty:
                pass
            due = (time.monotonic() - last_flush) >= self.cfg.flush_interval
            if batch and (len(batch) >= self.cfg.batch_size or due):
                self._flush(batch)
                batch = []
                last_flush = time.monotonic()
        if batch:
            self._flush(batch)

    def _flush(self, batch: list[dict]) -> None:
        payload = IngestBatch(spans=batch).to_wire()
        headers = {}
        if self.cfg.ingest_key:
            headers["X-Prism-Key"] = self.cfg.ingest_key
        url = self.cfg.collector_url.rstrip("/") + "/v1/ingest"
        for attempt in range(3):
            try:
                resp = self._client.post(url, json=payload, headers=headers)
                if resp.status_code < 300:
                    return
                log.debug("prism: collector %s -> %s", url, resp.status_code)
            except Exception as exc:  # noqa: BLE001
                log.debug("prism: ingest attempt %d failed: %s", attempt + 1, exc)
            time.sleep(0.2 * (attempt + 1))
        # Give up — never block or raise; count the loss.
        self.cfg.incr_dropped(len(batch))

    def flush(self, timeout: float = 2.0) -> None:
        """Best-effort drain (used on shutdown / tests)."""
        deadline = time.monotonic() + timeout
        while not self.q.empty() and time.monotonic() < deadline:
            time.sleep(0.02)

    def shutdown(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass


def start_transport(cfg: Config) -> Optional[SpanTransport]:
    return SpanTransport(cfg).start()
