# Ready-to-run examples

Drop-in samples referenced by [../GETTING_STARTED.md](../GETTING_STARTED.md).

## `prompts/` — a sample versioned prompt repo
Layout is `<root>/<app>/<name>/vN.prompt` (frontmatter + body). Here: an app
`support_bot` with `triage` (v1 **and** v2 — so you can see the diff) and `reply`
(which takes a `{tone}` variable).

Point the dashboard at it to use the **Prompts** tab:
```bash
prism dashboard --db ~/prism/prism.db --port 8052 \
  --prompts-dir docs/examples/prompts
```
Then: Prompts tab → app `support_bot` → prompt `triage` → version `v2` to see the
**v1 → v2 diff** and per-version usage.

Load them in code:
```python
from prism.prompts import PromptRepo
repo = PromptRepo("docs/examples/prompts")
p = repo.load("support_bot", "triage")        # latest (v2)
print(p.ref, "->", p.render())                # 'support_bot/triage@v2'
reply = repo.load("support_bot", "reply").render(tone="empathetic")
```

## `golden.json` — a reference set for `prism eval --references`
A list of `{"input": "<prompt>", "reference": "<expected output>"}`. The eval engine
hashes each `input` (SHA-256) and, for any captured span whose **input matches**,
scores the response against the reference with **ROUGE-L** (PASS/WARN/FAIL).

```bash
prism eval --db ~/prism/prism.db --collector http://127.0.0.1:9100 \
  --references docs/examples/golden.json
```

> **Important:** matching is by exact input hash. The `input` strings here must equal
> what your app actually sends as the user message for the match to fire. Treat this
> file as a template — replace the inputs/references with your own real test cases.
