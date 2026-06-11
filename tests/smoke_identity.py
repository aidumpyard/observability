"""Identity smoke: GET /auth/detail returns the identities; project_for scoping."""

import os
import tempfile

from prism.store import init_db


def main():
    db_path = os.path.join(tempfile.mkdtemp(), "id.db")
    init_db(db_path)
    os.environ["PRISM_IDENTITIES"] = "admin;bank1:prj_aaa;bank2:prj_bbb"

    from prism.dashboard import identity
    from prism.dashboard.app import create_app

    assert identity.names() == ["admin", "bank1", "bank2"], identity.names()
    assert identity.project_for("admin") is None
    assert identity.project_for("bank1") == "prj_aaa"
    assert identity.project_for("bank2") == "prj_bbb"

    app = create_app(db_path=db_path)
    client = app.server.test_client()

    # no password gate anymore — dashboard is open
    assert client.get("/").status_code == 200, "dashboard should be open (no Basic auth)"

    r = client.get("/auth/detail")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert body == {"identities": ["admin", "bank1", "bank2"]}, body

    os.environ.pop("PRISM_IDENTITIES", None)
    print("✅ IDENTITY OK — /auth/detail -> admin/bank1/bank2, no password, scoping map correct")


if __name__ == "__main__":
    main()
