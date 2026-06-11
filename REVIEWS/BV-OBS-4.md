# Self-review — BV-OBS-4

Per the owner's call, replaced password Basic-Auth (BV-OBS-3) with an **identity
endpoint**: `GET /auth/detail` → `["admin","bank1","bank2"]`, and a header identity
selector that scopes the dashboard (admin = all, bankN = its project, enforced
server-side).

## Scores (1–5)
| Dimension | Score | Why |
|---|---|---|
| Correctness & reliability | 4 | Endpoint + scoping tested; tenant lock enforced in `_render` (not just UI). Project dropdown disabled for tenant identities. |
| Sellability vs Grafana/Langfuse | 3.5 | A clean identity API (`/auth/detail`) is a good integration seam — an external SSO/proxy can map a real login to an identity. BUT, on its own this is **selection, not authentication**: anyone can pick `admin`. Net security is *lower* than BV-OBS-3 unless fronted by a proxy. Scored down honestly. |
| Onboarding / UX | 4 | Much smoother than a browser Basic-Auth prompt; identities are obvious and switchable; the endpoint is easy to integrate. |
| Performance & footprint | 4.5 | Zero deps; trivial route. |
| Code quality | 4 | Small `identity.py`; single scoping seam reused in dropdown + `_render`. |
| Test coverage | 3.5 | Endpoint + map covered; the dropdown→scope path verified by construction, not an automated UI test. |

## Overall verdict: 3.8 / 5
A better *product* seam (an API to drive identity, integrable with real auth) but a
deliberate **security step back** taken on the owner's instruction — there's no secret,
so it must sit behind an auth proxy / SSO that sets the identity. The right next move
is to make that explicit: let `/auth/detail` reflect an upstream-authenticated user
(e.g. a header/token from a proxy) rather than a free dropdown.

## Top 3 next actions (feed-forward)
1. **Bind identity to an upstream signal** — read the identity from a trusted header
   (e.g. `X-Prism-Identity` set by a proxy/SSO) or a signed token, so it isn't freely
   selectable; keep `/auth/detail` as the discovery endpoint. Restores real isolation.
2. **LLM-judge + Quality view** — still the headline differentiator vs Langfuse.
3. **One-command install** (`prism up`) + quickstart — frictionless trial.
