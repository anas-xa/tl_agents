# UI/UX improvement prompt

A reusable brief for redesigning the Smart Licence Services portal. It was written from a screenshot audit
of every screen, for every persona, in English and Arabic, on desktop and mobile. Hand it to a designer,
a front-end engineer or a coding agent as-is. Section 6 splits the work so several people or agents can
run it at the same time without touching the same files.

---

## 1. Role and goal

You are a senior product designer and front-end engineer. You are redesigning the web portal of **Smart
Licence Services**: AI-assisted tax, audit and compliance services sold as an optional add-on to a Dubai
trade licence and run by DET (Dubai Department of Economy and Tourism). The product works. It is accurate,
bilingual and accessible. But it looks like an internal prototype. Screens are long, dense and flat, so
users cannot see at a glance what matters.

**Goal:** make every screen calm, trustworthy and scannable, at the level of a premium government fintech
product (think UAE PASS, Emirates NBD business banking, Stripe Dashboard). Within five seconds on any
screen, users should know:
1. where they are and who they are acting as,
2. what needs their attention now,
3. what the one main action is.

## 2. Users

| Persona | What they need from the UI |
|---|---|
| Khalid, owner of a small trading company (often on mobile, Arabic or English) | Deadlines, what is ready, what is missing, one clear "approve" or "upload" step. No jargon. |
| Omar, delegate accountant handling several companies | Fast switching, dense but readable lists, bulk scanning. |
| Dr. Layla, licensed auditor; Hassan, tax specialist | Queues, evidence, decisions, deadlines. Workspace feel. |
| Sara (DET administrator), Ahmed (DET complaint handler) | Programme KPIs, trends, requests, SLA clocks. Executive-dashboard feel. |
| Noura, compliance reviewer | Audit trail and configuration register: tables, filters, pagination, exports. |

## 3. Non-negotiables (do not break these)

- **Bilingual and RTL.** Every change must work in Arabic (`dir="rtl"`) and English. Use logical CSS
  properties only (`margin-inline-start`, `inset-inline-end`, `padding-inline`). No `left` or `right`.
  Keep `<bdi>` around names and identifiers, and keep numbers and IDs left-to-right.
- **Accessibility (WCAG 2.2 AA).** Touch targets at least 44×44 px, visible keyboard focus on controls,
  contrast ≥ 4.5:1 for text, status always shown with icon *and* text (never colour alone), headings in
  order, `role`/`aria-*` kept as is. Respect `prefers-reduced-motion`.
- **Honesty labels stay visible.** "AI-prepared, not human approved", "Proposed wording - pending
  confirmation", "Example amounts", "Demo data", "Provisional", "Filed (user-confirmed)", "Not tax advice"
  are regulatory requirements. You may make them quieter (smaller, grouped, one per section instead of one
  per row) but never remove or hide them.
- **No behaviour changes.** Same data, same API calls, same permissions, same routes, same wording
  meaning. Rewording UI copy for clarity is allowed. Legal and compliance sentences stay as written.
- **Residency.** No external network calls from the browser: no CDNs and no Google Fonts at runtime.
  Fonts and icons are bundled.
- **No new heavy dependencies.** No UI kit or CSS framework. Plain CSS with tokens, plus small React
  components in `src/components/ui.tsx`. Inline SVG icons.

## 4. What the audit found

**Global**
1. A 3 px blue focus ring sits around the whole content area on every page (the `<main>` element gets
   focus after navigation and shows `:focus-visible`).
2. No visual identity: a plain text brand, flat white panels, an unchanged system font, and emoji and text
   glyphs used as nav icons (⌂ 🔎 📄 👥 ☷ ▦) that don't match.
3. "Acting as …" appears twice (a full-width blue strip and a pill on the page).
4. Chip overload: every row carries 2–4 bordered pills ("AI-prepared, draft · Under review" + "Demo data").
   Chips wrap and push content down.
5. Form controls outside `.field` are unstyled native controls (filters on the audit trail and DET dashboard).
6. Tables: dates wrap into six lines ("16 / October / 2026, / 10:59 / Dubai / time"), raw codes are shown
   (`AUDIT_TRAIL_VIEWED`, `data_access`), and there is no pagination.
7. Tabs wrap onto two rows (DET dashboard has 10 tabs).
8. Page headers are inconsistent: some pages have a subtitle, some a pill, some a badge, all in
   different places.

**Screens**
- **Owner dashboard:** 6,300 px tall. Panels stacked in a single column with half-empty side columns,
  and "Loading…" skeletons for panels further down. Needs a summary row, prioritised attention items, and
  a two-column layout where secondary panels are compact.
- **Return review:** the "Open" action looks like a broken button. The waiting item does not stand out as
  the main task.
- **Consent Centre:** 3,500 px. Eight "Not yet available / Notify me" bank rows take a whole screen.
- **DET dashboard:** KPI tiles have uneven heights, centred "Definition of …" links, and the key number
  is not visually dominant. Ten tabs wrap.
- **Audit trail:** 18,000 px, 100 rows, no pagination, dates wrapping, raw event codes.
- **Configuration register:** 59,000 px tall. Needs grouping, collapsed rows, search and pagination.
- **Auditor workspace, case queue, requests:** a lone table on an empty page. Needs a header with counts,
  a short "what to do next" line, and a good empty state.

## 5. Design direction

- **Tone:** calm, precise, official. Lots of white space, few colours, clear hierarchy.
- **Typography:** IBM Plex Sans Arabic (bundled with `@fontsource`; it covers Arabic and Latin) in one
  family for both languages. Use tabular numerals for money and dates. Type scale: 28 / 22 / 18 / 16 / 14 / 12.
  Arabic line height 1.8.
- **Colour:** keep the DET-like deep green accent (`#0f6e56`) as the only brand colour. Use a cool
  neutral grey ramp for surfaces and borders, status colours only for status, and tinted (not bordered)
  chips.
- **Shape:** 12 px radius for cards, 8 px for controls, soft shadows (`0 1px 2px` + `0 4px 16px` at low
  alpha), 1 px borders in `--border`.
- **Layout:** centred content up to 1200 px, a 24 px page gutter (16 px on mobile), and a consistent
  `PageHeader` (eyebrow, title, subtitle, actions, meta). A sticky top bar with a brand mark. A sidebar
  with SVG icons, a tinted active state and an accent bar.
- **Components:** `PageHeader`, `StatCard` (big number, label, trend, status), `Pagination`, `Toolbar`
  (filters row), `Tabs` (single row, scrolls horizontally), `ListRow`, `EmptyState` with a next step,
  `Disclosure`, and `ChipGroup` (shows the first 2 chips and folds the rest into "+n").
- **Density:** owners get comfortable spacing. Staff tables get compact rows (40 px) with `white-space:
  nowrap` on dates, IDs and amounts.
- **Progressive disclosure:** secondary detail (rule versions, refresh timestamps, definitions) goes
  into a `<details>` or a muted meta line, not the main reading line.
- **Mobile (390 px):** single column, no horizontal page scroll, sticky primary action where useful,
  tables turn into stacked cards or scroll inside their own container.

## 6. Work split (each stream owns its files; no two streams edit the same file)

0. **Foundation (do first):** `src/styles.css`, `src/components/ui.tsx`, `src/shell/*`, a new
   `src/components/Icon.tsx`, and fonts. Tokens, base element styles, components, shell, and the focus-ring fix.
1. **Owner home:** `features/dashboard/*` and every `DashboardPanel`/`InboxPanel`/`WhatsLivePanel`
   rendered on the dashboard.
2. **Owner workflows:** `features/tax/*` (except `DashboardPanel`), `features/approvals/*` (except
   `ComplianceTab`), `features/audit/AuditPage.tsx`, `features/documents/*`.
3. **Owner settings and support:** `features/consent/*` (except `DashboardPanel`),
   `features/subscription/*` (except `CohortTab`), `features/settings/*` (except `DetDelegationOverview`),
   `features/activity/*`, `features/help/*`, `features/portfolio/*`, `features/deadlines/*`,
   `features/reminders/ReminderSettings.tsx`.
4. **DET and specialists:** `features/det/*` (except `WhatsLivePanel`, `ResidencyStatement`),
   `features/kpis/*`, `features/detops/*`, `features/cases/*`, `features/auditor/*`,
   `features/subscription/CohortTab.tsx`, `features/approvals/ComplianceTab.tsx`,
   `features/settings/DetDelegationOverview.tsx`.
5. **Oversight and entry:** `features/core/*` (audit trail, configuration register, staff roles, home),
   `src/shell/SignIn.tsx`, `AuthComplete.tsx`, `StaticPage.tsx`, `features/demo/*`.

Rules for streams 1–5: use the foundation components and tokens. Put screen-specific CSS in a
`<feature>.css` file next to your components and import it from them (never edit `src/styles.css`).
If a shared component is missing, build it locally in your feature and name it in your report. Do not
change backend code, i18n keys used by other features, or tests owned by others. You may add i18n keys
in your own feature's `i18n.ts`.

## 7. Acceptance criteria

- No `<main>` focus ring after navigation. Keyboard focus is still clearly visible on controls.
- Every page starts with the same `PageHeader` pattern.
- Owner dashboard ≤ 2,600 px tall at 1440×900 with demo data. The first screen shows the deadline summary
  and the top attention items.
- Audit trail and configuration register are paginated (25 rows per page) or grouped and collapsed. No
  page is taller than about 4,000 px.
- Dates, amounts and IDs never wrap inside table cells. Raw codes are humanised ("Audit trail viewed").
- DET KPI tiles share a height in each row, and the key figure is the most prominent element.
- Tabs never wrap. They scroll horizontally on narrow screens.
- At 390 px wide, no screen scrolls horizontally.
- Arabic screens mirror correctly. Nothing overlaps or is clipped.
- `npx tsc -p tsconfig.app.json --noEmit`, `npx vitest run`, `npx oxlint`, `npx vite build` and the
  backend `pytest` all pass. The 12-chapter guided demo (`/demo`) still runs end to end in both languages.

## 8. How to verify

Run `./start.sh` (it serves on http://localhost:8000). For live editing, run `npx vite --port <port>` in
`frontend/` (it proxies `/api` to :8000). Sign in as a persona through the sandbox UAE PASS
(`/api/auth/start` then `…&persona=<key>`) and take screenshots at 1440×900 and 390×844, in both languages,
before and after. Compare page heights and check the criteria above.
