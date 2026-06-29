"""Seed the Prism collector with realistic ``loan_agent`` demo traffic.

Drives the real Prism SDK -> collector path (through the fake gateway) so every
column the dashboard reads gets populated: ``user_id``, ``session_id``, prompt
versions, tokens, status. Run it once per tenant, passing that tenant's ingest
key.

Env vars::

    KEY                 (required)  this tenant's ingest key (pk_...)
    USERS               (required)  comma-separated user ids, e.g. "alice,bob,carol"
    APP                 app name (default "loan_agent")
    N                   number of traces to generate (default 18)
    SEED                RNG seed for reproducibility (default 0)
    GATEWAY_URL         fake gateway (default http://127.0.0.1:8400/api/llm/process)
    PRISM_COLLECTOR_URL collector base (default http://127.0.0.1:9100)

Example::

    KEY=pk_xxx USERS="alice,bob,carol" N=21 SEED=1 python scripts/demo/seed.py
"""
import os
import random
import time

import prism

KEY = os.environ["KEY"]
APP = os.environ.get("APP", "loan_agent")
USERS = os.environ["USERS"].split(",")
N = int(os.environ.get("N", "18"))
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8400/api/llm/process")
COLLECTOR = os.environ.get("PRISM_COLLECTOR_URL", "http://127.0.0.1:9100")
random.seed(int(os.environ.get("SEED", "0")))

prism.init(app=APP, endpoint=GATEWAY, collector_url=COLLECTOR, ingest_key=KEY,
           env="prod", app_type="langgraph", verify=False, capture_io=True)

# Two document flavours so the fake gw returns PASS vs CONCERN (status/quality vary).
DOCS = [
    "Term sheet — client_name: Acme Manufacturing Pvt Ltd. value USD 2,500,000. tenure 48 months.",
    "Term sheet — client_name: Orion Energy Holdings Ltd. value USD 30 million cross-border. tenure 60 months.",
    "Term sheet — client_name: Acme Manufacturing Pvt Ltd. value USD 750,000. tenure 24 months.",
]
# Mix prompt versions so the by-prompt / quality-by-prompt tables show A/B rows.
RISK_PROMPTS = ["loan_agent/agent_risk@v1", "loan_agent/agent_risk@v2"]

for i in range(N):
    user = random.choice(USERS)
    session = f"sess_{user}_{i // 3}"     # a few traces share a session
    doc = random.choice(DOCS)
    with prism.trace("loan_process", user_id=user, session_id=session):
        prism.llm.generate(
            message=doc,
            system_prompt="You are an extraction engine. Return JSON loan features.",
            model="gemini-2.5-flash", prompt_id="loan_agent/extract@v1",
        )
        prism.llm.generate(
            message=doc,
            system_prompt="You are a credit risk auditor. Return a verdict.",
            model="gemini-2.5-flash", prompt_id=random.choice(RISK_PROMPTS),
        )
    time.sleep(0.02)

prism.shutdown(timeout=10.0)
print(f"seeded {N} traces for {APP} across users={USERS} (dropped={prism.dropped()})")
