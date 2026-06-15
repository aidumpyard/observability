"""Audit / reproducibility — tamper-evident hashing of inputs and outputs.

Every captured LLM span carries a SHA-256 of its (full) input and output, computed
at capture time *before* truncation/redaction — so you get a tamper-evident
fingerprint even when the text itself isn't stored. Together with the model,
reported model version, and sampler params, the input hash forms a "reproduction
key": replay these and (at temperature 0) you should get the same output; the output
hash proves you did. (prod_monitor.py's hash-logging idea, native to Prism.)
"""

from __future__ import annotations

import hashlib
from typing import Optional


def sha256(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify(stored_hash: Optional[str], text: Optional[str]) -> bool:
    """True iff sha256(text) matches the stored hash (tamper / match check)."""
    return bool(stored_hash) and sha256(text) == stored_hash


def repro_key(span: dict) -> dict:
    """The parameters needed to reproduce an output, plus the proof hashes."""
    params = span.get("params") if isinstance(span.get("params"), dict) else {}
    return {
        "model": span.get("model"),
        "temperature": params.get("temperature"),
        "input_hash": span.get("input_hash"),
        "output_hash": span.get("output_hash"),
    }
