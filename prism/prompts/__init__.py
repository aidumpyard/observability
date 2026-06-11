"""Directory-backed, versioned prompt repository (Phase 4).

Prompts live as plain files on disk, namespaced by application:

    <root>/<app_id>/<name>/v<N>.prompt

Each file is frontmatter (``key: value`` lines between ``---`` fences) plus a
template body. Latest version = highest ``N``. Pure Python, no extra deps, and
usable with or without Prism observability initialized — so products can load
prompts even when telemetry is turned off.

    repo = PromptRepo("loan_agent/prompts")
    p = repo.load("loan_agent", "extract")        # latest
    text = p.render()                              # or p.render(role="Fraud Analyst")
    p.ref                                          # 'loan_agent/extract@v1'
"""

from .repo import Prompt, PromptRepo, default_root

__all__ = ["Prompt", "PromptRepo", "default_root"]
