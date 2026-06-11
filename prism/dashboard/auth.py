"""Dashboard auth — HTTP Basic, zero extra deps (Flask under Dash).

Configured by env:
- ``PRISM_DASHBOARD_PASSWORD`` (+ optional ``PRISM_DASHBOARD_USER``, default "admin")
  → a single full-access admin.
- ``PRISM_DASHBOARD_USERS`` = ``user:pass:project; user2:pass2`` → multiple users.
  A user's optional 3rd field binds them to one project, so they only ever see that
  tenant's data (per-client logins for a multi-tenant deployment).

If neither is set, the dashboard is open (dev mode).
"""

from __future__ import annotations

import os
import secrets
from typing import Optional


def parse_users() -> dict:
    users: dict[str, dict] = {}
    pwd = os.environ.get("PRISM_DASHBOARD_PASSWORD")
    if pwd:
        users[os.environ.get("PRISM_DASHBOARD_USER", "admin")] = {"password": pwd, "project": None}
    for entry in os.environ.get("PRISM_DASHBOARD_USERS", "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            users[parts[0]] = {"password": parts[1],
                               "project": parts[2] if len(parts) > 2 and parts[2] else None}
    return users


def check(users: dict, username: Optional[str], password: Optional[str]) -> bool:
    u = users.get(username or "")
    return bool(u) and secrets.compare_digest(password or "", u["password"])


def install(server, users: dict) -> None:
    """Register a Basic-Auth gate on the Dash Flask server."""
    if not users:
        return
    from flask import Response, request

    @server.before_request
    def _gate():  # noqa: ANN202
        auth = request.authorization
        if auth and check(users, auth.username, auth.password):
            return None
        return Response("Authentication required", 401,
                        {"WWW-Authenticate": 'Basic realm="Prism"'})


def current_username(users: dict) -> Optional[str]:
    if not users:
        return None
    try:
        from flask import request
        a = request.authorization
        return a.username if a else None
    except Exception:  # noqa: BLE001 — outside a request context
        return None


def user_project(users: dict, username: Optional[str]) -> Optional[str]:
    """The project a user is restricted to, or None for full access."""
    u = users.get(username or "")
    return u["project"] if u else None
