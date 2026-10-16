import { Suspense, useEffect, useState, type ComponentType, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Placeholder } from '../../components/Placeholder'
import { Slot, useSlotEntries } from '../../components/Slot'
import { AiLabel, Button, Chip, Disclosure, Empty, Ident, Message, PageHeader, Panel, Skeleton, StatCard } from '../../components/ui'
import { post } from '../../lib/api'
import { daysLeftLabel, formatDate, formatDateTime } from '../../lib/format'
import { deviceOffsetFromDubai, tierTone, useBi, useFetch } from '../deadlines/lib'
import Compliance from './Compliance'
import RemoteStrip, { RemoteFreshness } from './RemoteStrip'
import type { Dashboard as DashboardData, MiniObligation, PanelData } from './types'
import './dashboard.css'

const CARD_TYPES = ['vat_return', 'ct_return', 'licence_renewal', 'ejari_renewal'] as const
type CardType = (typeof CARD_TYPES)[number]

/** Where each panel sits: action items in the main column, compact status panels in the side column. */
const MAIN_ORDER = ['compliance', 'deadlines', 'slot:data-links']
const SIDE_ORDER = ['tax_status', 'slot:tax', 'audit_status', 'slot:audit', 'documents', 'slot:reminders-inbox']
/** Deadline data that loaded normally is shown with the summary row (its freshness, source and full list);
 * any other state keeps its own panel so the problem stays visible. */
const INLINE_DEADLINE_STATES = ['fresh', 'last_known']

/** SC3 Company dashboard (Home): deadline summary row, next steps, then a two-column grid of panels with source,
 * last-updated and per-panel freshness; alerts strip; delegate locked placeholders; remote-owner variant. */
export default function Dashboard() {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const { me, companyId, can } = useAuth()
  const { data, error, loading, reload } = useFetch<DashboardData>(companyId ? `/api/companies/${companyId}/dashboard` : null)
  const remembered = useFetch<{ state: string; company_id: string | null; note: { en: string; ar: string } | null }>('/api/me/remembered-company')
  const slots = useSlotEntries('dashboard.panels')
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    setSlow(false)
    const id = setTimeout(() => setSlow(true), 5000)
    return () => clearTimeout(id)
  }, [companyId])
  if (!me) return null
  if (!companyId || me.companies.length === 0) return <Placeholder variant="B" title={t('no_companies')} />
  if (error && !data) {
    return <Message kind="error">{error.message} <Button variant="link" onClick={reload}>{t('retry')}</Button></Message>
  }
  if (!data) {
    return (
      <div className="dash" aria-busy="true">
        <PageHeader eyebrow={t('eyebrow')} title={t('title')} subtitle={loading && slow ? t('still_loading') : t('welcome')} />
        <div className="dash-deadlines" aria-hidden="true">
          {CARD_TYPES.map((c) => <div key={c} className="stat-card dash-skeleton-card"><Skeleton rows={3} /></div>)}
        </div>
        <div className="dash-cols" aria-hidden="true">
          <div className="dash-col"><div className="panel dash-skeleton-panel"><Skeleton rows={6} /></div></div>
          <div className="dash-col"><div className="panel dash-skeleton-panel"><Skeleton rows={6} /></div></div>
        </div>
      </div>
    )
  }
  const ar = i18n.language.startsWith('ar')
  const name = ar ? data.company.trade_name_ar : data.company.trade_name_en
  const deadlines = data.panels.find((p) => p.panel === 'deadlines')
  const items: MiniObligation[] = deadlines?.data?.items ?? []
  const offset = deviceOffsetFromDubai()
  const showDubaiNote = offset !== 0 && (data.acting_as.owner_abroad || data.view === 'remote_owner')
  const panelProps = { reload, canPrepare: can('compliance.prepare', companyId), canApprove: can('compliance.approve', companyId), isOwner: data.acting_as.company_role === 'owner' }
  const byName = (n: string) => data.panels.find((p) => p.panel === n)
  const slotById = (id: string) => slots.find((s) => s.id === id)
  const shared = deadlines?.freshness_state !== 'not_shared'
  const inlineDeadlines = !!deadlines && INLINE_DEADLINE_STATES.includes(deadlines.freshness_state)
  const render = (key: string) => {
    if (key.startsWith('slot:')) {
      const s = slotById(key.slice(5))
      return s ? <SlotPanel key={key} element={s.element as ComponentType} /> : null
    }
    if (key === 'deadlines' && inlineDeadlines) return null
    const p = byName(key)
    return p ? <PanelBox key={key} p={p} {...panelProps} /> : null
  }
  // When the licence requirements are locked or empty the main column is short: move Documents across to balance.
  const compliance = byName('compliance')
  const lightMain = !compliance || compliance.freshness_state === 'not_shared' || !!compliance.data?.empty
  const mainOrder = lightMain ? [...MAIN_ORDER, 'documents'] : MAIN_ORDER
  const sideOrder = lightMain ? SIDE_ORDER.filter((k) => k !== 'documents') : SIDE_ORDER
  const keys = [...mainOrder, ...sideOrder]
  const placed = new Set(keys.filter((k) => !k.startsWith('slot:')))
  const placedSlots = new Set(keys.filter((k) => k.startsWith('slot:')).map((k) => k.slice(5)))
  const extraPanels = data.panels.filter((p) => !placed.has(p.panel))
  const extraSlots = slots.filter((s) => !placedSlots.has(s.id))
  const delegateAccess = data.acting_as.role === 'delegate' && (data.acting_as.held_functions.length > 0 || data.acting_as.owner_only_functions.length > 0)
  return (
    <div className="dash">
      <PageHeader
        id="dash-title"
        eyebrow={data.company.licence_number ? <>{t('eyebrow_licence')} <Ident>{data.company.licence_number}</Ident></> : t('eyebrow')}
        title={<bdi>{name}</bdi>}
        subtitle={t('welcome')}
        meta={showDubaiNote ? <span className="dash-meta-item"><Icon name="clock" size={16} />{t('dubai_note', { offset: Math.abs(offset), dir: offset > 0 ? t('ahead') : t('behind') })}</span> : undefined}
      />
      {delegateAccess && <DelegateAccess d={data} />}
      <section aria-label={t('alerts')} className="dash-alerts">
        {remembered.data?.note && <Message kind="info">{tx(remembered.data.note)}</Message>}
        {data.licence_banner && <Message kind={data.licence_banner.kind === 'licence_expired' ? 'error' : 'warning'}>{tx(data.licence_banner.text)}</Message>}
        <Slot name="dashboard.alerts" />
        {data.alerts.map((a, i) => (
          <Message key={i} kind={a.severity === 'critical' ? 'error' : a.severity === 'info' ? 'info' : 'warning'}>
            {tx(a.text)} {a.link && <Link to={a.link}>→</Link>}
          </Message>
        ))}
        {data.remote && <RemoteFreshness remote={data.remote} />}
        {data.not_shared_note && <Message kind="info">{tx(data.not_shared_note)}</Message>}
      </section>
      {shared && <DeadlineSummary items={items} k10={tx(data.k10_tile)} panel={inlineDeadlines ? deadlines : undefined} hideWithheld={!!data.not_shared_note} />}
      <div className="dash-cols">
        <div className="dash-col dash-col-main">
          {data.remote && <RemoteStrip remote={data.remote} companyId={companyId} onChange={reload} />}
          <NextSteps d={data} />
          {mainOrder.map(render)}
        </div>
        <div className="dash-col dash-col-side">
          {sideOrder.map(render)}
          {extraPanels.map((p) => <PanelBox key={p.panel} p={p} {...panelProps} />)}
          {extraSlots.filter((s) => s.id !== 'whats-live').map((s) => <SlotPanel key={s.id} element={s.element as ComponentType} />)}
        </div>
      </div>
      {slotById('whats-live') && extraSlots.some((s) => s.id === 'whats-live') && (
        <div className="dash-wide">
          <SlotPanel element={slotById('whats-live')!.element as ComponentType} />
        </div>
      )}
    </div>
  )
}

/** One slot panel with a placeholder of similar height while its code loads, so the layout does not jump. */
function SlotPanel({ element: El }: { element: ComponentType }) {
  return (
    <Suspense fallback={<div className="panel dash-skeleton-panel" aria-hidden="true"><Skeleton rows={3} /></div>}>
      <El />
    </Suspense>
  )
}

/** Delegates see which functions they hold and which stay with the owner (the shell already says who they act as). */
function DelegateAccess({ d }: { d: DashboardData }) {
  const { t } = useTranslation('dashboard')
  const a = d.acting_as
  const fn = (f: string) => t(`held_fn.${f}`, { defaultValue: f.replace(/_/g, ' ') })
  return (
    <Disclosure summary={t('your_access')} className="dash-access">
      <dl className="kv">
        <dt>{t('held_functions')}</dt>
        <dd>{a.held_functions.map(fn).join(t('list_sep'))}</dd>
        {a.owner_only_functions.length > 0 && (
          <>
            <dt>{t('owner_only')}</dt>
            <dd>{a.owner_only_functions.map((f) => t(`owner_only_list.${f}`)).join(t('list_sep'))}</dd>
          </>
        )}
      </dl>
    </Disclosure>
  )
}

function soonest(items: MiniObligation[], type: CardType): MiniObligation | undefined {
  return items.filter((x) => x.obligation_type === type).sort((a, b) => (a.days_left ?? 99999) - (b.days_left ?? 99999))[0]
}

/** The four key deadlines as a summary row, most urgent first and marked as such (text, not only colour). */
function DeadlineSummary({ items, k10, panel, hideWithheld }: { items: MiniObligation[]; k10: string; panel?: PanelData; hideWithheld: boolean }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const cards = CARD_TYPES.map((type) => ({ type, o: soonest(items, type) })).sort((a, b) => {
    const da = a.o?.due_date ? a.o.days_left ?? 99999 : 100000
    const db = b.o?.due_date ? b.o.days_left ?? 99999 : 100000
    return da - db
  })
  const anyDemo = cards.some((c) => c.o?.is_demo)
  const list: MiniObligation[] = panel?.data?.items ?? []
  const next = list.find((o) => o.due_date && o.days_left !== null && o.days_left >= 0) ?? list[0]
  return (
    <section aria-labelledby="status-cards-title" className="dash-summary" id={panel ? 'panel-deadlines' : undefined}>
      <div className="section-title dash-section-title">
        <h2 id="status-cards-title">{t('status_cards')}</h2>
        <span className="dash-section-end">
          {anyDemo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}
          {panel && <Freshness p={panel} />}
          <Link to="/deadlines">{t('open_deadlines')}</Link>
        </span>
      </div>
      <div className="dash-deadlines">
        {cards.map((c, i) => <DeadlineCard key={c.type} type={c.type} o={c.o} top={i === 0 && !!c.o?.due_date && c.o.days_left !== null} />)}
      </div>
      <div className="dash-summary-foot">
        <p className="dash-source">
          {panel?.source && <span>{t('source', { source: panel.source })}</span>}
          {panel?.last_updated && <span>{t('last_updated', { time: formatDateTime(panel.last_updated, i18n.language) })}</span>}
          <span>{t('k10_label')}: {k10}</span>
          {panel?.data?.withheld_note && !hideWithheld && <span>{tx(panel.data.withheld_note)}</span>}
        </p>
        {list.length > 0 && (
          <Disclosure className="dash-deadlines-all" summary={<>{t('deadlines_count', { count: list.length })}{next && <span className="dash-deadlines-next"> · {t('deadlines_next', { name: tx(next.name), date: next.due_date ? formatDate(next.due_date, i18n.language) : t('date_not_confirmed') })}</span>}</>}>
            <MiniList items={list} />
          </Disclosure>
        )}
      </div>
    </section>
  )
}

function DeadlineCard({ type, o, top }: { type: CardType; o: MiniObligation | undefined; top: boolean }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const lang = i18n.language
  if (!o) {
    return (
      <div className="dash-deadline" role="group" aria-label={`${t(`card_type.${type}`)}, ${t('no_card')}`}>
        <StatCard icon="calendar" label={t(`card_type.${type}`)} value={<span className="dash-deadline-none">{t('no_card')}</span>} />
      </div>
    )
  }
  const tt = tierTone(o.days_left_tier)
  const tone = tt.tone === 'neutral' ? undefined : tt.tone
  const ready = o.readiness === 'draft_ready' || o.readiness === 'owner_approved'
  const label = `${tx(o.name)}, ${o.due_date ? formatDate(o.due_date, lang) : t('date_not_confirmed')}, ${o.days_left !== null ? daysLeftLabel(o.days_left, lang) : ''}, ${t('missing_n', { n: o.missing_items.length })}`
  return (
    <div className={`dash-deadline ${top ? `dash-deadline-top dash-tone-${tt.tone}` : ''}`} role="group" aria-label={label}>
      <StatCard
        icon="calendar"
        tone={tone}
        label={<>{t(`card_type.${type}`)}{top && <span className="dash-top-flag">{t('most_urgent')}</span>}</>}
        value={o.due_date ? <span className="nowrap">{formatDate(o.due_date, lang)}</span> : <span className="dash-deadline-none">{t('no_card')}</span>}
        status={o.due_date ? (o.days_left !== null ? <Chip tone={tt.tone} icon={tt.icon}>{daysLeftLabel(o.days_left, lang)}</Chip> : null) : <Chip tone="info" icon="?">{t('date_not_confirmed')}</Chip>}
        footer={
          <div className="dash-deadline-ready">
            <div>
              {o.missing_items.length ? <Chip tone="attention" icon="!">{t('missing')}</Chip> : ready ? <Chip tone="ok" icon="✓">{t('prepared')}</Chip> : null}{' '}
              <span className="muted">{tx(o.readiness_label)}</span>
            </div>
            {o.missing_items.length > 0 && <ul className="dash-missing">{o.missing_items.map((m) => <li key={m.code}>{i18n.language.startsWith('ar') ? m.label_ar : m.label_en}</li>)}</ul>}
          </div>
        }
      />
    </div>
  )
}

function NextSteps({ d }: { d: DashboardData }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  return (
    <Panel title={<>{t('next_steps')}{d.next_steps.length > 0 && <span className="tab-badge dash-count">{d.next_steps.length}</span>}</>} id="next-steps" className="dash-next">
      {d.next_steps.length === 0 ? <p className="muted">{t('no_next_steps')}</p> : (
        <ol className="dash-steps">
          {d.next_steps.map((s, i) => (
            <li key={i} className="dash-step">
              <span className="dash-step-num" aria-hidden="true">{i + 1}</span>
              <div className="dash-step-main">
                <div className="dash-step-title">{s.link ? <Link to={s.link}>{tx(s.title)}</Link> : tx(s.title)}</div>
                {(s.due_date || s.status_label || s.items?.length || s.ai_prepared) && (
                  <div className="dash-step-meta">
                    {s.due_date && <span className="nowrap"><Icon name="calendar" size={14} /> {formatDate(s.due_date, i18n.language)}</span>}
                    {s.status_label && <span>{tx(s.status_label)}</span>}
                    {s.items && s.items.length > 0 && <span>{t('missing_n', { n: s.items.length })}</span>}
                    {s.ai_prepared && <AiLabel />}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}

type BoxProps = { p: PanelData; reload: () => void; canPrepare: boolean; canApprove: boolean; isOwner: boolean }

/** Freshness chip (icon + text) for a panel header, with source and last update as one quiet line underneath. */
function Freshness({ p }: { p: PanelData }) {
  const { t } = useTranslation('dashboard')
  const tone = p.freshness_state === 'fresh' ? 'ok' : p.freshness_state === 'last_known' ? 'attention' : p.freshness_state === 'not_linked_yet' ? 'neutral' : 'critical'
  return <Chip tone={tone} icon={p.freshness_state === 'fresh' ? '✓' : p.freshness_state === 'last_known' ? '◷' : '!'}>{t(`freshness.${p.freshness_state}`)}</Chip>
}

function SourceLine({ p }: { p: PanelData }) {
  const { t, i18n } = useTranslation('dashboard')
  if (!p.source && !p.last_updated) return null
  return (
    <p className="dash-source">
      {p.source && <span>{t('source', { source: p.source })}</span>}
      {p.last_updated && <span>{t('last_updated', { time: formatDateTime(p.last_updated, i18n.language) })}</span>}
    </p>
  )
}

function PanelBox({ p, reload, canPrepare, canApprove, isOwner }: BoxProps) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const { companyId } = useAuth()
  const [sent, setSent] = useState<string | null>(p.request_access?.state === 'sent' ? p.request_access.sent_at ?? null : null)
  const title = t(`panels.${p.panel}`)
  if (p.freshness_state === 'not_shared') {
    const request = async () => {
      const out = await post<{ sent_at: string }>(`/api/companies/${companyId}/dashboard/request-access`, { panel: p.panel })
      setSent(out.sent_at)
    }
    return (
      <Panel title={<span className="dash-title-icon"><Icon name="lock" size={18} />{title}</span>} id={`panel-${p.panel}`} className="dash-locked">
        <p className="muted">{t('not_shared')}</p>
        {sent ? (
          <Button variant="secondary" aria-disabled="true" disabled>{t('request_sent', { date: formatDate(sent, i18n.language) })}</Button>
        ) : (
          <Button variant="secondary" onClick={request}>{t('request_access')}</Button>
        )}
      </Panel>
    )
  }
  if (p.freshness_state === 'not_available' || p.freshness_state === 'could_not_be_loaded') {
    return (
      <Panel title={title} id={`panel-${p.panel}`} actions={<Freshness p={p} />}>
        <SourceLine p={p} />
        <Message kind="error">
          {p.panel === 'deadlines' ? t('error_deadlines') : tx(p.message)} {p.reason_code === 'SOURCE_TIMEOUT_NO_CACHE' && <span className="helper">({t('timeout_reason')} <Ident>{p.reason_code}</Ident>)</span>}
        </Message>
        <Button variant="secondary" onClick={reload}>{t('retry')}</Button>
      </Panel>
    )
  }
  const headerLink = p.panel === 'deadlines' ? <Link to="/deadlines">{t('open_deadlines')}</Link> : null
  return (
    <Panel title={title} id={`panel-${p.panel}`} actions={<>{headerLink}<Freshness p={p} /></>}>
      {p.panel !== 'documents' && <SourceLine p={p} />}
      {p.freshness_state === 'cannot_be_confirmed' && <Message kind="warning">{tx(p.message)} · {t('stale_note', { time: formatDateTime(p.last_good_time, i18n.language) })}</Message>}
      {p.freshness_state === 'not_linked_yet' && <p><strong>{t('not_linked_yet')}</strong></p>}
      {p.data && <PanelBody p={p} reload={reload} canPrepare={canPrepare} canApprove={canApprove} isOwner={isOwner} />}
    </Panel>
  )
}

function PanelBody({ p, reload, canPrepare, canApprove, isOwner }: BoxProps) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const d = p.data
  switch (p.panel) {
    case 'tax_status': {
      const lines: { en: string; ar: string; unconfirmed?: boolean; unconfirmed_label?: { en: string; ar: string } }[] = d.lines ?? []
      const dl: MiniObligation[] = d.deadlines ?? []
      return (
        <div>
          {lines.length > 0 && (
            <ul className="dash-lines">
              {lines.map((l, i) => <li key={i}>{tx(l)} {l.unconfirmed !== false && <Chip tone="info" icon="?">{l.unconfirmed_label ? tx(l.unconfirmed_label) : t('unconfirmed')}</Chip>}</li>)}
            </ul>
          )}
          {d.next_step && <p className="dash-next-link"><Link to="/deadlines">{tx(d.next_step)}</Link></p>}
          {d.audit_required_line && <p className="helper">{tx(d.audit_required_line)}</p>}
          {(dl.length > 0 || d.sbr) && (
            <Disclosure summary={dl.length > 0 ? t('tax_deadlines', { n: dl.length }) : t('show_details')}>
              <MiniList items={dl} />
              {d.sbr && <p><strong>{t('sbr_title')}: </strong>{tx(d.sbr.text)}</p>}
              <p className="muted">{t('k10_label')}: {tx(d.k10)}</p>
            </Disclosure>
          )}
        </div>
      )
    }
    case 'audit_status':
      return (
        <div>
          <p className="dash-audit-state"><strong>{d.state_label ? tx(d.state_label) : t('audit_not_assessed')}</strong>{d.badge && <> <Chip tone="info" icon="i">{tx(d.badge)}</Chip></>}</p>
          {d.reason && <p>{typeof d.reason === 'string' ? d.reason : tx(d.reason)}</p>}
          <p className="helper">{t('audit_note')}{d.last_updated_label ? ` ${tx(d.last_updated_label)}` : ''}</p>
        </div>
      )
    case 'deadlines': {
      const list: MiniObligation[] = d.items ?? []
      const next = list.find((o) => o.due_date && o.days_left !== null && o.days_left >= 0) ?? list[0]
      return (
        <div>
          {list.length === 0 ? <p className="muted">{t('no_card')}</p> : (
            <Disclosure className="dash-deadlines-all" summary={<>{t('deadlines_count', { count: list.length })}{next && <span className="dash-deadlines-next"> · {t('deadlines_next', { name: tx(next.name), date: next.due_date ? formatDate(next.due_date, i18n.language) : t('date_not_confirmed') })}</span>}</>}>
              <MiniList items={list} />
            </Disclosure>
          )}
          {d.withheld_note && <p className="helper">{tx(d.withheld_note)}</p>}
        </div>
      )
    }
    case 'documents': {
      type Doc = { document_id: string; title: string; title_ar: string; review_label: { en: string; ar: string }; link: string | null; is_demo: boolean }
      const docs: Doc[] = d.items ?? []
      return (
        <div>
          {docs.length === 0 ? <Empty icon="file" title={t('documents_empty')} /> : (
            <>
              <p className="dash-labels"><span className="muted">{t('applies_all')}</span><AiLabel />{docs.some((x) => x.is_demo) && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}</p>
              <ul className="dash-rows">
                {docs.map((x) => {
                  const title = i18n.language.startsWith('ar') ? x.title_ar : x.title
                  return (
                    <li key={x.document_id} className="dash-row">
                      <span className="dash-row-main">{x.link ? <Link to={x.link}>{title}</Link> : <span>{title}</span>}</span>
                      <span className="dash-row-end muted">{tx(x.review_label)}</span>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
          <p className="dash-source">
            {p.source && <span>{t('source', { source: p.source })}</span>}
            {p.last_updated && <span>{t('last_updated', { time: formatDateTime(p.last_updated, i18n.language) })}</span>}
            <span>{t('k28_label')}: {tx(d.k28)}</span>
          </p>
        </div>
      )
    }
    case 'compliance':
      return <Compliance data={d} onChange={reload} canPrepare={canPrepare} canApprove={canApprove} isOwner={isOwner} />
    default:
      return null
  }
}

function MiniList({ items }: { items: MiniObligation[] }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  if (!items.length) return null
  return (
    <ul className="dash-mini">
      {items.slice(0, 6).map((o) => {
        const tt = tierTone(o.days_left_tier)
        const status: ReactNode = o.missing_items.length > 0 ? <Chip tone="attention" icon="!">{t('missing')}</Chip> : o.readiness === 'draft_ready' ? <Chip tone="ok" icon="✓">{t('prepared')}</Chip> : null
        return (
          <li key={o.obligation_id}>
            <span className="dash-mini-name">{tx(o.name)}{o.calculated && o.due_date ? <span className="muted"> · {t('calculated')}</span> : null}</span>
            <span className="dash-mini-date">{o.due_date ? <span className="nowrap">{formatDate(o.due_date, i18n.language)}</span> : <Chip tone="info" icon="?">{t('date_not_confirmed')}</Chip>}</span>
            <span className="dash-mini-chips">
              {o.days_left !== null && <Chip tone={tt.tone} icon={tt.icon}>{daysLeftLabel(o.days_left, i18n.language)}</Chip>}
              {status}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
