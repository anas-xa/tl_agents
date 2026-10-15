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
| Backend API | `backend/` | FastAPI, SQLAlchemy 2.0, SQLite by default (Postgres via `QEONIX_DATABASE_URL`) |
| Portal | `frontend/` | React 19, Vite, TypeScript, react-i18next; Arabic RTL and English at parity |
| Mock UAE PASS | `backend/app/modules/identity/mock_uaepass.py` | OIDC provider with test personas; swap for staging by configuration |
| Local model | `backend/app/modules/localmodel/` | Deterministic rules adapter by default; local HTTP adapter behind the residency allow-list |
| Registers | `/api/admin/config`, `/api/admin/rules` | Versioned configuration and rule-version register with owner, status and effective date |
| Docs | `docs/` | Architecture, build conventions, phase map |

## Run it

```bash
# backend
cd backend
uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev]"
python -m app.cli seed-demo          # reference data + demo companies and personas
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

Open http://localhost:5173, pick a language, press **Sign in with UAE Pass** and choose a test persona
(owner Khalid, remote owner Priya, delegate Omar, licensed auditor Layla, DET administrator Sara, DET pilot
manager Faisal, compliance reviewer Noura, tax specialist Hassan, legal specialist Mariam, and the refusal
cases: SOP1 account, no company role, owner without an Emirates ID on the DET record).

Or with containers: `docker compose up --build` (backend on 8000, portal on 5173).

## Tests and checks

```bash
cd backend && . .venv/bin/activate && python -m pytest -q && ruff check app tests
cd frontend && npx tsc -b && npx vite build
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
