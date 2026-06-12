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


def cmd_up(db: str | None = None, collector_port: int = 9100, dashboard_port: int = 8052,
           prompts_dir: str | None = None, eval: bool = False, judge_url: str | None = None,
           ssl_keyfile: str | None = None, ssl_certfile: str | None = None) -> None:
    """One command: launch collector + dashboard (+ optional eval loop) together."""
    import os
    import signal
    import subprocess
    import time
    db = db or default_db_path()
    init_db(db)
    env = dict(os.environ, PRISM_DB=db)
    py = sys.executable
    procs: list = []

    def launch(label: str, args: list):
        procs.append((label, subprocess.Popen([py, "-m", "prism.cli"] + args, env=env)))

    serve = ["serve", "--db", db, "--port", str(collector_port)]
    if ssl_keyfile:
        serve += ["--ssl-keyfile", ssl_keyfile, "--ssl-certfile", ssl_certfile or ""]
    launch("collector", serve)

    dash = ["dashboard", "--db", db, "--port", str(dashboard_port)]
    if prompts_dir:
        dash += ["--prompts-dir", prompts_dir]
    launch("dashboard", dash)

    if eval:
        ev = ["eval", "--watch", "--db", db,
              "--collector", f"http://127.0.0.1:{collector_port}"]
        if judge_url:
            ev += ["--judge-url", judge_url]
        launch("eval-loop", ev)

    scheme = "https" if ssl_keyfile else "http"
    print("prism up:")
    print(f"  collector  {scheme}://127.0.0.1:{collector_port}")
    print(f"  dashboard  http://127.0.0.1:{dashboard_port}")
    print(f"  db         {db}" + ("  + eval loop" if eval else ""))
    print("  (Ctrl-C to stop all)")

    stopping = {"v": False}
    signal.signal(signal.SIGINT, lambda *a: stopping.update(v=True))
    signal.signal(signal.SIGTERM, lambda *a: stopping.update(v=True))
    try:
        while not stopping["v"]:
            time.sleep(0.5)
            for label, p in procs:
                if p.poll() is not None:
                    print(f"  '{label}' exited (code {p.returncode}) — stopping the rest")
                    stopping["v"] = True
                    break
    finally:
        for label, p in procs:
            if p.poll() is None:
                p.terminate()
        for label, p in procs:
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
        print("prism up: stopped")


def cmd_project(action: str, name: str | None = None, db: str | None = None) -> None:
    from .store import ProjectsDAO, default_db_path
    dao = ProjectsDAO(db or default_db_path())
    if action == "create":
        if not name:
            sys.exit("usage: prism project create <name>")
        p = dao.create(name)
        print(f"created project '{p['name']}'")
        print(f"  project_id : {p['project_id']}")
        print(f"  ingest_key : {p['ingest_key']}")
        print("\nUse it in the product:")
        print(f"  prism.init(app=\"<app>\", endpoint=..., collector_url=..., "
              f"ingest_key=\"{p['ingest_key']}\")")
    elif action == "list":
        rows = dao.list()
        if not rows:
            print("no projects yet — `prism project create <name>`")
            return
        for r in rows:
            print(f"  {r['project_id']}  {r['name']}  active={r['active']}  {r['created_at']}")
    else:
        sys.exit(f"unknown project action: {action}")


def cmd_eval(db: str | None = None, collector: str = "http://127.0.0.1:9100",
             judge_url: str | None = None, judge_model: str = "gemini-2.5-flash",
             sample: float = 1.0, ingest_key: str | None = None,
             references: str | None = None, watch: bool = False,
             interval: float = 300.0, max_judge: int | None = None) -> None:
    from .evals import runner
    from .store import default_db_path
    db = db or default_db_path()
    judge = None
    if judge_url:
        from .evals.judge import GatewayJudge
        judge = GatewayJudge(judge_url, model=judge_model)
    refs = None
    if references:
        from .evals.reference import load_references
        refs = load_references(references)
    kw = dict(judge=judge, sample=sample, ingest_key=ingest_key, references=refs,
              max_judge=max_judge)
    if watch:
        runner.run_loop(db, collector, interval=interval, **kw)   # scheduled, incremental
    else:
        res = runner.run(db, collector, **kw)
        print(f"eval: scored={res['scores']} accepted={res['accepted']} "
              f"judge={res['judge']} references={res['references']}")


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
    def up(db: str = None, collector_port: int = 9100, dashboard_port: int = 8052,
           prompts_dir: str = None, eval: bool = False, judge_url: str = None,
           ssl_keyfile: str = None, ssl_certfile: str = None):
        """Launch collector + dashboard (+ --eval loop) together."""
        cmd_up(db, collector_port, dashboard_port, prompts_dir, eval, judge_url,
               ssl_keyfile, ssl_certfile)

    @app.command()
    def dashboard(host: str = "127.0.0.1", port: int = 8052, db: str = None,
                  debug: bool = False, show_cost: bool = False, prompts_dir: str = None):
        cmd_dashboard(host, port, db, debug, show_cost, prompts_dir)

    @app.command()
    def prompts(action: str, target: str = typer.Argument(None), root: str = None):
        """list  |  show <app>/<name>[@vN]"""
        cmd_prompts(action, target, root)

    @app.command()
    def project(action: str, name: str = typer.Argument(None), db: str = None):
        """create <name>  |  list"""
        cmd_project(action, name, db)

    @app.command(name="eval")
    def eval_(db: str = None, collector: str = "http://127.0.0.1:9100",
              judge_url: str = None, judge_model: str = "gemini-2.5-flash",
              sample: float = 1.0, ingest_key: str = None, references: str = None,
              watch: bool = False, interval: float = 300.0, max_judge: int = None):
        """Score recent spans (heuristics + optional judge/references). --watch loops."""
        cmd_eval(db, collector, judge_url, judge_model, sample, ingest_key, references,
                 watch, interval, max_judge)

    app()


def _argparse_main() -> None:
    import argparse
    p = argparse.ArgumentParser(prog="prism")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init"); pi.add_argument("--db")
    ps = sub.add_parser("serve")
    ps.add_argument("--host", default="0.0.0.0"); ps.add_argument("--port", type=int, default=9100)
    ps.add_argument("--db"); ps.add_argument("--ssl-keyfile"); ps.add_argument("--ssl-certfile")
    pu = sub.add_parser("up")
    pu.add_argument("--db"); pu.add_argument("--collector-port", type=int, default=9100)
    pu.add_argument("--dashboard-port", type=int, default=8052); pu.add_argument("--prompts-dir")
    pu.add_argument("--eval", action="store_true"); pu.add_argument("--judge-url")
    pu.add_argument("--ssl-keyfile"); pu.add_argument("--ssl-certfile")
    pd_ = sub.add_parser("dashboard")
    pd_.add_argument("--host", default="127.0.0.1"); pd_.add_argument("--port", type=int, default=8052)
    pd_.add_argument("--db"); pd_.add_argument("--debug", action="store_true")
    pd_.add_argument("--show-cost", action="store_true"); pd_.add_argument("--prompts-dir")
    pp = sub.add_parser("prompts")
    pp.add_argument("action", choices=["list", "show"])
    pp.add_argument("target", nargs="?"); pp.add_argument("--root")
    pj = sub.add_parser("project")
    pj.add_argument("action", choices=["create", "list"])
    pj.add_argument("name", nargs="?"); pj.add_argument("--db")
    pe = sub.add_parser("eval")
    pe.add_argument("--db"); pe.add_argument("--collector", default="http://127.0.0.1:9100")
    pe.add_argument("--judge-url"); pe.add_argument("--judge-model", default="gemini-2.5-flash")
    pe.add_argument("--sample", type=float, default=1.0); pe.add_argument("--ingest-key")
    pe.add_argument("--references")
    pe.add_argument("--watch", action="store_true"); pe.add_argument("--interval", type=float, default=300.0)
    pe.add_argument("--max-judge", type=int)
    a = p.parse_args()
    if a.cmd == "init":
        cmd_init(a.db)
    elif a.cmd == "serve":
        cmd_serve(a.host, a.port, a.db, a.ssl_keyfile, a.ssl_certfile)
    elif a.cmd == "up":
        cmd_up(a.db, a.collector_port, a.dashboard_port, a.prompts_dir, a.eval,
               a.judge_url, a.ssl_keyfile, a.ssl_certfile)
    elif a.cmd == "dashboard":
        cmd_dashboard(a.host, a.port, a.db, a.debug, a.show_cost, a.prompts_dir)
    elif a.cmd == "prompts":
        cmd_prompts(a.action, a.target, a.root)
    elif a.cmd == "project":
        cmd_project(a.action, a.name, a.db)
    elif a.cmd == "eval":
        cmd_eval(a.db, a.collector, a.judge_url, a.judge_model, a.sample, a.ingest_key,
                 a.references, a.watch, a.interval, a.max_judge)


if __name__ == "__main__":
    main()
