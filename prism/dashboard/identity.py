"""Identity selection (no passwords).

The dashboard exposes ``GET /auth/detail`` which returns the available identities,
e.g. ``["admin", "bank1", "bank2"]``. The user picks one in the header; ``admin``
sees every project, a tenant identity (bank1/bank2) is scoped to its project.

Configured via env ``PRISM_IDENTITIES`` as ``name[:project_id]`` entries separated
by ``;`` — e.g. ``admin;bank1:prj_abc;bank2:prj_def``. ``admin`` is always present
and unscoped. With nothing configured, only ``admin`` exists.

This is identity *selection*, not authentication — there is no secret. Put a real
auth proxy in front if you need to actually restrict access.
"""

from __future__ import annotations

import os
from typing import Optional


def config() -> dict:
    """identity name -> project_id (None = admin / all projects)."""
    out: dict[str, Optional[str]] = {}
    for entry in os.environ.get("PRISM_IDENTITIES", "admin").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        out[parts[0]] = parts[1] if len(parts) > 1 and parts[1] else None
    out.setdefault("admin", None)
    return out


def names() -> list[str]:
    return list(config().keys())


def project_for(identity: Optional[str]) -> Optional[str]:
    """The project an identity is locked to, or None (admin / all)."""
    return config().get(identity or "admin")
