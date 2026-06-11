"""Dashboard auth smoke: 401 without creds, 200 with, wrong rejected; per-project
user binding. Uses the Dash app's Flask test client (no server)."""

import base64
import os
import tempfile

from prism.store import init_db


def _hdr(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def main():
    db_path = os.path.join(tempfile.mkdtemp(), "auth.db")
    init_db(db_path)
    os.environ["PRISM_DASHBOARD_PASSWORD"] = "s3cret"
    os.environ["PRISM_DASHBOARD_USERS"] = "acme:pw:prj_123"

    from prism.dashboard.app import create_app
    from prism.dashboard import auth

    app = create_app(db_path=db_path)
    client = app.server.test_client()

    assert client.get("/").status_code == 401, "open access must be blocked"
    assert client.get("/", headers=_hdr("admin", "s3cret")).status_code == 200, "admin login"
    assert client.get("/", headers=_hdr("admin", "wrong")).status_code == 401, "bad pw"
    assert client.get("/", headers=_hdr("acme", "pw")).status_code == 200, "tenant login"
    assert client.get("/", headers=_hdr("nobody", "x")).status_code == 401, "unknown user"

    users = auth.parse_users()
    assert auth.user_project(users, "admin") is None, "admin = full access"
    assert auth.user_project(users, "acme") == "prj_123", "tenant bound to project"

    for k in ("PRISM_DASHBOARD_PASSWORD", "PRISM_DASHBOARD_USERS"):
        os.environ.pop(k, None)
    print("✅ AUTH OK — 401 gate, admin + tenant logins, per-project binding")


if __name__ == "__main__":
    main()
