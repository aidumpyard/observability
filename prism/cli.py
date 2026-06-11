"""Prism CLI: `prism init`, `prism serve`.

Uses typer if installed, else falls back to a tiny argparse shim so the package
stays importable without the `cli` extra.
"""

from __future__ import annotations

import os
import sys

from .store import default_db_path, init_db
from .version import __version__


def cmd_init(db: str | None = None) -> None:
    path = db or default_db_path()
    init_db(path)
    print(f"prism: initialized store at {path}")


def cmd_serve(host: str = "0.0.0.0", port: int = 9100, db: str | None = None,
              ssl_keyfile: str | None = None, ssl_certfile: str | None = None) -> None:
    if db:
        os.environ["PRISM_DB"] = db
    try:
        import uvicorn
    except ImportError:
        sys.exit("prism serve needs the 'collector' extra: pip install prism-observability[collector]")
    uvicorn.run(
        "prism.collector:app", host=host, port=port, workers=1,  # single writer (B1)
        ssl_keyfile=ssl_keyfile, ssl_certfile=ssl_certfile,
    )


def cmd_dashboard(host: str = "127.0.0.1", port: int = 8052, db: str | None = None,
                  debug: bool = False, show_cost: bool = False, prompts_dir: str | None = None) -> None:
    try:
        from .dashboard.app import run as run_dashboard
    except ImportError:
        sys.exit("prism dashboard needs the 'dashboard' extra: pip install prism-observability[dashboard]")
    run_dashboard(db_path=db, host=host, port=port, debug=debug, show_cost=show_cost,
                  prompts_root=prompts_dir)


def cmd_prompts(action: str, target: str | None = None, root: str | None = None) -> None:
    from .prompts import PromptRepo
    repo = PromptRepo(root)
    if action == "list":
        apps = repo.list_apps()
        if not apps:
            print(f"prism: no prompts under {repo.root}")
            return
        for app in apps:
            for name in repo.list_prompts(app):
                vers = repo.versions(app, name)
                print(f"  {app}/{name}  versions={vers}")
    elif action == "show":
        if not target or "/" not in target:
            sys.exit("usage: prism prompts show <app>/<name>[@vN]")
        p = repo.resolve(target)
        print(f"# {p.ref}  (vars: {', '.join(p.variables) or 'none'})\n")
        print(p.template)
    else:
        sys.exit(f"unknown prompts action: {action}")


def main() -> None:
    try:
        import typer
    except ImportError:
        return _argparse_main()

    app = typer.Typer(help=f"Prism observability {__version__}")

    @app.command()
    def init(db: str = typer.Option(None, help="SQLite path (default ~/.prism/prism.db)")):
        cmd_init(db)

    @app.command()
    def serve(host: str = "0.0.0.0", port: int = 9100, db: str = None,
              ssl_keyfile: str = None, ssl_certfile: str = None):
        cmd_serve(host, port, db, ssl_keyfile, ssl_certfile)

    @app.command()
    def dashboard(host: str = "127.0.0.1", port: int = 8052, db: str = None,
                  debug: bool = False, show_cost: bool = False, prompts_dir: str = None):
        cmd_dashboard(host, port, db, debug, show_cost, prompts_dir)

    @app.command()
    def prompts(action: str, target: str = typer.Argument(None), root: str = None):
        """list  |  show <app>/<name>[@vN]"""
        cmd_prompts(action, target, root)

    app()


def _argparse_main() -> None:
    import argparse
    p = argparse.ArgumentParser(prog="prism")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init"); pi.add_argument("--db")
    ps = sub.add_parser("serve")
    ps.add_argument("--host", default="0.0.0.0"); ps.add_argument("--port", type=int, default=9100)
    ps.add_argument("--db"); ps.add_argument("--ssl-keyfile"); ps.add_argument("--ssl-certfile")
    pd_ = sub.add_parser("dashboard")
    pd_.add_argument("--host", default="127.0.0.1"); pd_.add_argument("--port", type=int, default=8052)
    pd_.add_argument("--db"); pd_.add_argument("--debug", action="store_true")
    pd_.add_argument("--show-cost", action="store_true"); pd_.add_argument("--prompts-dir")
    pp = sub.add_parser("prompts")
    pp.add_argument("action", choices=["list", "show"])
    pp.add_argument("target", nargs="?"); pp.add_argument("--root")
    a = p.parse_args()
    if a.cmd == "init":
        cmd_init(a.db)
    elif a.cmd == "serve":
        cmd_serve(a.host, a.port, a.db, a.ssl_keyfile, a.ssl_certfile)
    elif a.cmd == "dashboard":
        cmd_dashboard(a.host, a.port, a.db, a.debug, a.show_cost, a.prompts_dir)
    elif a.cmd == "prompts":
        cmd_prompts(a.action, a.target, a.root)


if __name__ == "__main__":
    main()
