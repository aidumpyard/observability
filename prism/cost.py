"""Cost computation from token counts.

A small built-in price table (USD per 1k tokens) keyed by model name, overridable
at init. Cost is computed at capture time and stored on the span so the dashboard
never has to join against a moving price list. Unknown models → cost is left None
(honest: we don't guess a price we don't have).
"""

from __future__ import annotations

from typing import Optional

# USD per 1,000 tokens. Extend/override via prism.init(cost_table=...).
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    # model: (input_per_1k, output_per_1k)
    "gemini-2.5-flash": (0.00015, 0.0006),
    "gemini-2.5-pro": (0.00125, 0.005),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini-1.5-pro": (0.00125, 0.005),
}


def compute_cost(
    model: Optional[str],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    table: Optional[dict] = None,
) -> Optional[float]:
    if not model or prompt_tokens is None or completion_tokens is None:
        return None
    prices = table or DEFAULT_PRICES
    rate = prices.get(model)
    if rate is None:
        # Try a prefix match (e.g. "gemini-2.5-flash-002" -> "gemini-2.5-flash").
        for key, val in prices.items():
            if model.startswith(key):
                rate = val
                break
    if rate is None:
        return None
    in_rate, out_rate = rate
    return round((prompt_tokens / 1000.0) * in_rate + (completion_tokens / 1000.0) * out_rate, 8)
