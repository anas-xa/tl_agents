# Qeonix Smart Licence Services (MVP)

AI business services for Dubai DET trade licences: a per-licence subscription embedded in licence issuance
and renewal, where local AI agents prepare tax, audit-preparation and compliance work for mainland companies,
with licensed-professional sign-off and owner approval wherever the rules require it.

This repository is the Phase 1 pilot build described in the R&D package: a bilingual (Arabic/English)
company portal, a DET administrator dashboard, specialist and auditor workspaces, and the registers that keep
every legal or commercial value as versioned, confirmable configuration.

## What is in the box

| Area | Where | Notes |
| --- | --- | --- |
| Backend API | `backend/` | FastAPI, SQLAlchemy 2.0, SQLite by default (Postgres via `QEONIX_DATABASE_URL`); 29 auto-discovered modules |
| Portal | `frontend/` | React 19, Vite, TypeScript, react-i18next; Arabic RTL and English at parity; 20 feature folders |
| Mock UAE PASS | `backend/app/modules/identity/mock_uaepass.py` | OIDC provider with test personas; swap for staging by configuration |
| Local model | `backend/app/modules/localmodel/` | Deterministic rules adapter by default; local HTTP adapter behind the residency allow-list |
| Registers | `/api/admin/config`, `/api/admin/rules` | About 570 versioned configuration keys and 65 rule-register entries, each with owner, status and effective date |
| Docs | `docs/` | Architecture and build conventions |

## Features by epic

| Epic | What the pilot build does | Main screens |
| --- | --- | --- |
| E1 Foundations | UAE PASS sign-in, per-company roles and role-combination rules, hash-chained audit trail, residency register and egress guard, phase map and integration checklist, availability probes, delegate management | Sign-in, Team and settings, Activity, Audit trail, DET residency and phase tabs |
| E2 Licence and subscription | DET licence intake with configurable mapping, per-licence subscription created only at the next licence event in the cohort, billing hook, payment allocation, opt-out, refunds and complaints, pilot cohort register | Welcome (SC2), Subscription, DET cohort tab, DET requests and complaints |
| E3 Dashboard and deadlines | Company dashboard, versioned deadline engine with no roll-forward, compliance agent with three confirmed rules, reminder templates with forbidden-content checks, delegate portfolio | Home (SC3), Deadlines (SC4), My companies (SC12), Reminders tab |
| E4 Consent and data | Consent store with four consent types, withdrawal timeline and receipt, manual statement upload under its own notice, empty ERP connector list, manual tax profile, link freshness | Consent Centre (SC5), Data links tab |
| E5 Tax preparation assistant | Fixed-rule classification, VAT and corporate-tax calculation with blocked states, draft return packs with the fixed watermark, injection-safe document handling | Tax workspace (SC6), draft viewer |
| E6 Approvals | Hash-bound owner approval with authority evidence, Phase B delegate grants switched off, manual filing states only, approval-compliance monitoring | Return review (SC7), Approval rights tab, DET approval compliance tab |
| E7 Audit agent and documents | Exception rules, audit-required indicator, draft audit working file, licensed-auditor review ("Record review"), bilingual documents with public verification | Audit preparation (SC8), Documents (SC9), Auditor workspace (SC13), `/verify/:code` |
| E8 Human escalation | Deterministic triggers, cases with consent-wait timeline, specialist entitlement checks, corpus answers with refusal, K21/K22 in working days | Help (SC10), Case queue |
| E9 DET dashboard | One shared small-group suppression engine, KPI catalogue and calculators, per-licence allow-list view, CSV export | DET dashboard (SC14) |

## Switched off until a regulator, DET or counsel confirms

These paths are built and tested in both states, and stay off by configuration:

- Live FTA filing, the EmaraTax tax-status link and Open Finance bank pulls.
- Delegate rights to grant consent, approve submissions and change the subscription.
- Default-on subscription billing; opt-in is the pilot default.
- Licensed-auditor signing and the Auditor's report document; auditors record a review instead.
- Lawyer routing, legal wording and legal Q&A; legal questions get a neutral message only.
- SMS and WhatsApp reminders; in-portal and outbox-only email are on.
- Virtual lawyer, remote-services agent, AML monitoring, other emirates and federal level.

The demo seed switches the tax-specialist escalation path on so the journey can be shown; its reference
default is off until the FTA position is recorded.

## Run it

**Easiest: one command.** You need [Python 3.12+](https://www.python.org/downloads/) and
[Node.js 20+](https://nodejs.org/). The first run installs everything (a few minutes); later runs start in
seconds. The app opens at http://localhost:8000 with the demo data loaded.

```bash
# macOS / Linux
./start.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

**With Docker instead** (no Python or Node needed): `docker compose up --build`, then open
http://localhost:8000. Data is kept in a Docker volume between runs.

Use another port with `PORT=9000 ./start.sh`. To start over with fresh demo data, delete `backend/data/`.

**For development** (hot reload on two ports):

```bash
cd backend && uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev]"
python -m app.cli seed-demo && uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173
```

## Tests and checks

```bash
cd backend && . .venv/bin/activate && python -m pytest -q && ruff check app tests   # about 440 tests, ~70 s
cd backend && python scripts/dependency_check.py                                     # no external model SDKs, telemetry or CDNs
cd frontend && npx tsc -b && npx vite build && npx vitest run
```

## Principles the build enforces

- UAE PASS is the only sign-in route; approval acts need the highest assurance level and a recorded act.
- Every data access, agent action, consent, approval, escalation and sign-off is written to a hash-chained,
  append-only audit trail with pseudonymous actor keys.
- Roles are held per company; combinations that would create self-approval or break a firewall are refused.
- Nothing is submitted to an authority automatically; Phase 1 filing is manual with an owner-recorded record.
- No unsigned output is ever called an audit certificate or audit report; drafts carry a fixed bilingual
  watermark.
- Local models only; outbound calls go through the residency egress guard and an allow-list that starts empty.
- Thresholds, windows, fees, wording versions and switches are configuration with an owner and a
  confirmation status, never code.

See `docs/ARCHITECTURE.md` for the module map and `docs/CONVENTIONS.md` for how features are built.
