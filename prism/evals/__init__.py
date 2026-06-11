"""Prism eval engine (Phase 3).

Offline scoring of captured spans. Heuristic scorers run with no LLM; the pluggable
remote LLM-judge (added incrementally) produces quality scores. Scores are written
back through the collector's ``/v1/scores`` endpoint — the eval engine is never a
direct DB writer (decision B1). Judge/eval traffic is tagged ``internal=eval`` so it
never pollutes product metrics.
"""

from .scorers import HEURISTICS, score_span

__all__ = ["HEURISTICS", "score_span"]
