# Prism demo helpers

Self-contained scripts that populate a Prism collector with realistic
`loan_agent` traffic — **no API keys, no real gateway**. Use them to see a fully
populated dashboard (overview, traces with `user_id`/`session_id`, quality, and
the user filter) on a fresh setup.

- **`fake_gw.py`** — a stand-in Gemini gateway on `127.0.0.1:8400` that returns a
  full envelope (with token usage) for the loan extraction + risk-audit prompts.
- **`seed.py`** — drives the real Prism SDK against that gateway, generating
  traces with `user_id` / `session_id` / prompt versions so every dashboard view
  fills in.

## Quick start

Assumes the collector is already running on `:9100` (e.g.
`prism serve --db ~/prism/demo.db --port 9100`). Use a separate terminal per
long-running process.

```bash
# 1. start the fake gateway (leave running)
python scripts/demo/fake_gw.py

# 2. create tenants, copy each ingest key (pk_...) + project id (prj_...)
prism project create "Acme Bank"      --db ~/prism/demo.db
prism project create "Globex Capital" --db ~/prism/demo.db

# 3. seed once per tenant
KEY=<acme_key>   USERS="alice,bob,carol" N=21 SEED=1 python scripts/demo/seed.py
KEY=<globex_key> USERS="dave,erin"       N=15 SEED=2 python scripts/demo/seed.py

# 4. score quality (heuristics)
prism eval --db ~/prism/demo.db --collector http://127.0.0.1:9100 --sample 1.0

# 5. launch the dashboard
PRISM_SHOW_WATERFALL=false PRISM_SHOW_QUALITY=true \
PRISM_IDENTITIES="admin;bank1:<acme_prj>;bank2:<globex_prj>" \
  prism dashboard --db ~/prism/demo.db --port 8052
```

On Windows, replace `prism ...` with `python -m prism.cli ...` if you run from
source, set env vars with `set NAME=value` (cmd) or `$env:NAME="value"`
(PowerShell), and open each long-running process in its own window. See
[`docs/GETTING_STARTED.md`](../../docs/GETTING_STARTED.md) for the full guide.
