"""N1 guarantee: Prism never throws into product code.

Every public SDK entry point routes through ``safe`` (decorator) or ``safe_call``.
A failure inside capture is logged at DEBUG and swallowed; the product proceeds as
if Prism weren't there. Errors that originate in the *product's own* wrapped
function are re-raised — we only ever absorb Prism's own failures.
"""

from __future__ import annotations

import functools
import logging

log = logging.getLogger("prism")


def safe_call(fn, *args, default=None, **kwargs):
    """Run a Prism-internal callable, swallowing any exception it raises."""
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 — deliberately broad; observability must not break products
        log.debug("prism: suppressed internal error in %s", getattr(fn, "__name__", fn), exc_info=True)
        return default


def safe(default=None):
    """Decorator form of :func:`safe_call` for Prism-internal helpers."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return safe_call(fn, *args, default=default, **kwargs)
        return wrapper
    return deco
