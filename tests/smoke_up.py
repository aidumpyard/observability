"""`prism up` smoke: one command brings up collector + dashboard; both serve; then
it tears everything down cleanly. Uses test ports so it won't clash with a running
stack."""

import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

CPORT, DPORT = 9111, 8062


def _get(url):
    try:
        return urllib.request.urlopen(url, timeout=2).status
    except Exception:  # noqa: BLE001
        return None


def main():
    db = os.path.join(tempfile.mkdtemp(), "up.db")
    # own process group so we can kill the whole tree
    p = subprocess.Popen(
        [sys.executable, "-m", "prism.cli", "up", "--db", db,
         "--collector-port", str(CPORT), "--dashboard-port", str(DPORT)],
        start_new_session=True)
    try:
        up = False
        for _ in range(40):
            time.sleep(1)
            if _get(f"http://127.0.0.1:{CPORT}/health") == 200 and \
               _get(f"http://127.0.0.1:{DPORT}/") == 200:
                up = True
                break
        assert up, "collector + dashboard did not both come up via `prism up`"
        # collector really is the prism collector
        import json
        h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CPORT}/health").read())
        assert h["status"] == "ok", h
        print("✅ UP OK — `prism up` launched collector + dashboard; both serving")
    finally:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)   # stop up + its children
        try:
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        # ports should be free again
        time.sleep(1)
        assert _get(f"http://127.0.0.1:{DPORT}/") is None, "dashboard still up after teardown"
        print("   teardown clean (ports released)")


if __name__ == "__main__":
    main()
