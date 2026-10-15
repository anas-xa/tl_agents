# Build conventions for the Qeonix platform (read before implementing an epic)

The product is an MVP of "Qeonix Smart Licence Services": a per-licence subscription embedded in Dubai DET trade
licence issuance/renewal, where AI agents prepare tax, audit-preparation and compliance work under human sign-off.
The R&D package (condensed per epic in the spec files you are given) is the source of truth. Build what the
spec says is in Phase 1; build-but-switch-off what it says is gated; demonstrate fixture-only states with
fixtures labelled "Demo data". Never invent legal values: hold them as configuration with status
`to_be_confirmed` and the label the spec gives.

## Repository layout

```
backend/            FastAPI + SQLAlchemy 2.0 (sync) + SQLite (dev/test) / Postgres via QEONIX_DATABASE_URL
  app/core/         settings, db (Base, SessionLocal, get_db), errors, ids, time
  app/modules/<m>/  one package per domain module (auto-discovered, see below)
  app/api/deps.py   get_principal, require(permission), require_staff(permission), client_ip
  app/api/auth.py   sign-in endpoints; app/api/admin.py config/rules/audit-trail/staff-roles
  app/seed.py       core reference seed; app/demo.py demo companies/licences/roles/personas
  tests/            pytest; conftest gives `client` (TestClient), `db`, and `sign_in(client, persona)`
frontend/           React 19 + Vite + TypeScript + react-i18next (ar/en, RTL)
  src/app/auth.tsx  useAuth(): me, companyId, company, can(permission), hasStaff(...), setLanguage
  src/shell/        topbar, side/bottom nav, company switcher, sign-in (SC1), idle timeout
  src/components/   ui.tsx (Chip, Panel, Message, Button, Field, Table, Dialog, Empty, Skeleton, AiLabel, Ident),
                    Placeholder.tsx (variants A/B/C), Slot.tsx (render slot entries)
  src/features/<f>/ one folder per feature; `register.ts` is auto-imported
  src/i18n/{en,ar}.json shell strings (features ship their own namespaces, see below)
  src/lib/api.ts    get/post/put/patch/del + ApiError; src/lib/format.ts dates/AED/days-left formatter
docs/               architecture, this file, phase map, registers
```

## Backend module pattern (auto-discovery: never edit main.py, models.py, seed.py, demo.py)

`app/modules/<name>/`
- `models.py`  SQLAlchemy models (`from app.core.db import Base`). Use `String` ids from `app.core.ids.new_id("prefix")`.
  Money is stored in **fils** as `Integer` (AED x 100). Dates `Date`, timestamps naive UTC `DateTime` via
  `app.core.time.utcnow()`. Enumerations are module-level tuples of strings; store the string.
- `service.py` pure functions `fn(db: Session, ...)`. No HTTP objects. Raise `app.core.errors` types
  (`NotFound`, `Forbidden`, `Conflict`, `ValidationFailed`, `SwitchedOff`).
- `api.py` exposes `router = APIRouter(prefix="/api/<name>", tags=[...])` (or `routers = [...]`).
  Company-scoped endpoints take `company_id` in the path and use
  `principal: Principal = Depends(require("<permission>"))` which enforces company isolation, the permission
  matrix, the Phase-B delegate-right switches and UAE PASS step-up for approval acts. Staff endpoints use
  `Depends(require_staff("<permission>"))`. Always `db.commit()` before returning.
- `seed.py` with `ORDER = <int>` (lower runs first; licences=10, subscriptions=20, consent=30, rules=40,
  bookkeeping=50, tax=55, approvals=60, audit=70, documents=75, escalation=80, det=90),
  `seed(db)` for reference data (use `ensure_config` / `ensure_rule` from `app.modules.config.service`) and
  `seed_demo(db)` for demo rows for the demo companies (`app.demo.CO_ALNOOR`, `CO_BLUEDUNE`, `CO_SAFWA`,
  `CO_GULFTECH`; persona UUIDs in `app.demo.PERSONA_UUIDS`). Seeds must be idempotent (check before insert).
- `tests/test_<name>.py` in `backend/tests/`. Drive flows through the API with `sign_in(client, persona)`.
  Personas: khalid (owner of Al Noor + Safwa, SOP3), priya (remote owner Blue Dune, SOP2 visitor),
  omar (delegate on Al Noor, Blue Dune, Gulf Tech; rights prepare+view), layla (licensed auditor),
  sara (det_admin + det_compliance_lead), faisal (det_pilot_manager), noura (compliance_reviewer),
  hassan (tax_specialist), mariam (legal_specialist), yusuf (escalation_ops), adel (platform_security_admin),
  lina (qeonix_product_owner), ahmed (det_complaint_handler), noroles, sop1 (refused), noeid (no owner role).

Permissions live in `app/modules/access/service.py` (`OWNER_PERMS`, `DELEGATE_BASE_PERMS`, `STAFF_PERMS`...).
If your story needs a new permission string, ADD it there (append to the right set; keep names
`<area>.<verb>`), and mention it in your report. Step-up permissions (consent/approval/subscription/grants)
are in `STEP_UP_PERMS`.

### Cross-cutting services you must use
- **Audit trail**: `from app.modules.audit.service import record_event` for every data access, agent action,
  consent, approval, escalation, sign-off, config change, reminder, billing event. Arguments:
  `event_type` (UPPER_SNAKE), `category` (sign_in|access|agent|consent|approval|escalation|sign_off|config|
  data_access|billing|document|reminder|system), `outcome`, `reason_code`, `actor_key=principal.actor_key`,
  `actor_role`, `company_id`, `subject_type`, `subject_id`, `details` (NO financial figures, identity numbers,
  bank account numbers or free text in details; references and codes only), `log_class`.
  Fail-closed actions: pass `fail_closed=True` and catch `AuditWriteError` to refuse.
- **Configuration**: `get_config(db, key, default)`, `ensure_config(...)`, `rule_params(db, rule_id)`,
  `ensure_rule(db, rule_id, title, instrument=..., status=..., owner_role=..., parameters={...})`.
  Key naming: `<module>.<setting>` (e.g. `fee.annual_amount_fils`, `approval.validity_days`). Every value the
  spec calls configurable/provisional/to-be-confirmed is a config key or a rule-register entry with the
  correct `status` and `label`. Thresholds, windows, wording versions, switches: all config, none in code.
- **Feature switches**: `get_config(db, "<module>.<feature>.enabled", False)`; refuse with `SwitchedOff` when
  off. Build the code path, keep it off, test both states.
- **Local model only**: AI classification/extraction goes through `app/modules/localmodel/client.py`
  (`get_local_model()` returning an adapter with `classify(...)`, `extract(...)`). The default adapter is
  deterministic rules; an Ollama-style HTTP adapter targets a local URL. Never call an external provider;
  never import an external-model SDK.
- **Residency**: no outbound network calls from modules except through `app.modules.hosting.egress.guard(url)`
  (built by the hosting module; if it does not exist yet, do not make outbound calls at all).

### Bilingual strings
Every user-facing string the spec lists must exist in both languages exactly as written. Backend strings that
end up in documents, notices, reminders, receipts, refusals or watermarks live in your module's
`strings.py` as `STRINGS = {"key": {"en": "...", "ar": "..."}}` plus an `audience_class` ("official"|"other")
map, and are registered with the catalogue via `from app.modules.catalogue.service import register_strings`
(if the catalogue module is absent at build time, keep the dict and the registration call behind a try/import).
Frontend strings go in `frontend/src/features/<f>/i18n.ts` which calls
`i18n.addResourceBundle('en', '<ns>', {...}); i18n.addResourceBundle('ar', '<ns>', {...})` and components use
`useTranslation('<ns>')`. Never hard-code UI text in JSX. Arabic text is a draft pending native review; copy
the spec's Arabic verbatim.

### Banned terms (tests must assert they never appear in unsigned outputs, titles, file names, watermarks)
"audit certificate", "audit report" (unsigned), "certified", "Compliant", "PDPL-compliant", "independent"
(firewall result), "Filed" when the platform did not file, "penalty applies", "Tax Agent" (use
"Tax preparation assistant"), "Included with your licence", "hosted in the UAE" without qualification,
"your data is deleted", "verified" for manual uploads.

## Frontend feature pattern (auto-discovery: never edit App.tsx, Shell.tsx, index.ts, registry.ts)

`frontend/src/features/<f>/register.ts`:
```ts
import { lazy } from 'react'
import { registerFeature, registerSlot, registerHome } from '../registry'
import './i18n'
registerFeature(
  [{ path: '/consent', element: lazy(() => import('./ConsentCentre')), permission: 'consent.view', scope: 'company' }],
  [{ path: '/consent', labelKey: 'nav.consent', icon: '✓', permission: 'consent.view', scope: 'company', order: 40 }],
)
registerSlot('dashboard.panels', { id: 'consent', labelKey: 'consent:panel', element: lazy(() => import('./DashboardPanel')), permission: 'consent.view', order: 50 })
```
Slots: `dashboard.panels` (SC3 status cards), `dashboard.alerts` (SC3 alert strip), `settings.tabs` (SC11),
`det.tabs` (SC14), `welcome.checklist` (SC2), `help.sections` (SC10). Nav order bands: Home 0, Deadlines 10,
Tax 20, Returns 25, Audit 30, Documents 35, Consent 40, Team 50, Help 60, Portfolio 15, Auditor 70,
Cases 72, DET 80, Audit trail 90, Admin 95. A role that lacks the permission gets Placeholder C automatically;
pass `fallback: 'A'` for features not in this phase.

Components: use `Panel`, `Chip` (icon + text, never colour alone), `Message` (role alert/status), `Button`
(44 px), `Field`, `Table`, `Dialog`, `Empty`, `Skeleton`, `AiLabel` (every AI output), `Ident` (identifiers in
Western digits, bidi-isolated). Format with `formatDate` (written month), `formatDateTime`, `formatAED`
(fils in), `daysLeftLabel`, `daysLeftTier`. Every screen defines its empty / loading / error / partial /
no-access states as the spec lists them. Keyboard operable; `dir` mirroring is automatic (logical CSS
properties only: `inset-inline-start`, `margin-inline-end`...). Do not add npm dependencies.

Data access: `get<T>('/api/...')` etc. from `src/lib/api.ts`; `ApiError.code` carries the backend reason
code (e.g. `RIGHT_SWITCHED_OFF`, `FEATURE_SWITCHED_OFF`, `NO_PERMISSION`), use it to show the spec's refusal
wording and disabled controls with reasons.

## Testing and quality gates
- Backend: `cd backend && . .venv/bin/activate && python -m pytest -q -p no:warnings tests/test_<name>.py`
  (run only your own test files while others are working; run the full suite at the end).
  `ruff check app tests` must pass for your files.
- Frontend: `cd frontend && npx tsc -b && npx vite build` must pass. Component tests with vitest are welcome
  (`npx vitest run`), not mandatory.
- Each acceptance criterion in your spec maps to at least one test or a documented fixture state.

## Working rules for implementers
- Own only your module folders, your feature folders, your test files, your `strings.py`/`i18n.ts`.
  Append-only edits are allowed in `access/service.py` (permission sets). Do not touch other modules'
  files; if you need something from another module, import it lazily and fall back gracefully (and say so
  in your report).
- Do not run `git commit`; the integrator commits. Do not install packages.
- Report back: modules built, endpoints, permissions added, config keys/rules seeded, switches and their
  defaults, fixtures, tests run with counts, anything from the spec you deliberately left out and why.
