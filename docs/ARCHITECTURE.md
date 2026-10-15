# Architecture

## Shape

```
 Browser (portal, ar/en)  ──►  FastAPI backend  ──►  SQLite / Postgres
        │                           │
        │  OIDC code + PKCE         ├── audit trail (hash chain, pending store, retention classes)
        ▼                           ├── config + rule registers (versioned, owner, status)
   UAE PASS (mock / staging)        ├── authorisation and consent enforcement (fail closed)
                                    ├── local model adapter (rules | local HTTP)  ── no external calls
                                    └── feature modules (auto-discovered)
```

The backend is a modular monolith. Every domain module under `backend/app/modules/<name>/` is discovered
automatically (`app/discovery.py`): its `models.py` is registered with the ORM, its `api.py` router is
mounted, and its `seed.py` seeds reference and demo data in `ORDER`. Modules talk to each other through
service functions, never through HTTP.

## Cross-cutting modules

| Module | Responsibility |
| --- | --- |
| `identity` | UAE PASS OIDC sign-in (mock provider included), sessions, staff-role table with two-person approval |
| `companies` | Companies and per-company roles (owner, remote owner, delegate, auditor, specialist, reviewer) |
| `access` | Permission matrix, company isolation, Phase-B delegate switches, step-up for approval acts, role-combination rules |
| `audit` | Append-only hash-chained events, pseudonymous actor keys, pending store, exports with second approver |
| `config` | Versioned configuration entries and the rule-version register |
| `catalogue` | Bilingual string catalogue with audience class, reviewer status and the release gate |
| `localmodel` | Local-model client; rules adapter by default |
| `licences` | DET licence records, persons (hashed Emirates ID), intake events |

Feature modules (built per epic) add licences and billing, consent and data links, bookkeeping and tax,
drafts and approvals, audit agent and documents, escalation, hosting and phase registers, and DET KPIs.

## Identity and access flow

1. `POST /api/auth/start` creates a pending sign-in (state, nonce, PKCE) and returns the UAE PASS URL.
2. UAE PASS redirects to `GET /api/auth/callback`; the ID token is validated against JWKS (signature,
   issuer, audience, nonce, expiry) and the assurance level against the versioned `identity.min_assurance_level`.
3. The Emirates ID on the assertion is hashed and matched to DET licence persons; no match means no owner role.
4. Roles are resolved per company from platform records only; a session cookie is set; the sign-in event is
   written fail-closed (no audit, no session).
5. Every request re-resolves roles (`get_principal`) and every endpoint declares its permission
   (`require("consent.grant")`); refusals are logged.

## Data principles

- Money in fils (integer), timestamps in UTC, displayed in Asia/Dubai.
- Identity numbers are never stored; only salted hashes for matching.
- Audit details carry references and codes, never figures or free text.
- Reference data that law or DET can change (thresholds, dates, fees, holidays) lives in registers with an
  instrument, effective date, owner and confirmation status.

## Frontend

React shell with role-based navigation, company switcher (hidden / static / list), language precedence
(explicit > profile > cookie > browser > Arabic), platform-wide numeral style, and three placeholder variants
for not-yet-available / empty / no-access states. Features register routes, navigation, home resolvers and
slot entries (dashboard panels, settings tabs, DET tabs, welcome checklist, help sections) from their own
`register.ts`, so shared screens compose without shared edits.
