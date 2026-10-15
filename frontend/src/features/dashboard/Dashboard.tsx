import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Placeholder } from '../../components/Placeholder'
import { Slot } from '../../components/Slot'
import { AiLabel, Button, Chip, Empty, Ident, Message, Panel, Skeleton } from '../../components/ui'
import { post } from '../../lib/api'
import { daysLeftLabel, formatDate, formatDateTime } from '../../lib/format'
import { deviceOffsetFromDubai, tierTone, useBi, useFetch } from '../deadlines/lib'
import Compliance from './Compliance'
import RemoteStrip from './RemoteStrip'
import type { Dashboard as DashboardData, MiniObligation, PanelData } from './types'

const CARD_TYPES = ['vat_return', 'ct_return', 'licence_renewal', 'ejari_renewal'] as const

/** SC3 Company dashboard (Home): five panels with source, last-updated and per-panel freshness; status cards;
 * next steps; alerts strip; delegate locked placeholders; remote-owner variant. */
export default function Dashboard() {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const { me, companyId, can } = useAuth()
  const { data, error, loading, reload } = useFetch<DashboardData>(companyId ? `/api/companies/${companyId}/dashboard` : null)
  const remembered = useFetch<{ state: string; company_id: string | null; note: { en: string; ar: string } | null }>('/api/me/remembered-company')
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
      <div aria-busy="true">
        <h1>{t('title')}</h1>
        {loading && slow && <p>{t('still_loading')}</p>}
        <Skeleton rows={6} />
      </div>
    )
  }
  const name = i18n.language.startsWith('ar') ? data.company.trade_name_ar : data.company.trade_name_en
  const deadlines = data.panels.find((p) => p.panel === 'deadlines')
  const items: MiniObligation[] = deadlines?.data?.items ?? []
  const offset = deviceOffsetFromDubai()
  const showDubaiNote = offset !== 0 && (data.acting_as.owner_abroad || data.view === 'remote_owner')
  return (
    <div>
      <header style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <div>
          <h1 style={{ marginBottom: 4 }}><bdi>{name}</bdi></h1>
          <p className="helper" style={{ margin: 0 }}>{t('welcome')} {data.company.licence_number && <>· DET <Ident>{data.company.licence_number}</Ident></>}</p>
          {showDubaiNote && <p className="helper">{t('dubai_note', { offset: Math.abs(offset), dir: offset > 0 ? t('ahead') : t('behind') })}</p>}
        </div>
        <ActingAs d={data} />
      </header>
      {remembered.data?.note && <Message kind="info">{tx(remembered.data.note)}</Message>}
      {data.licence_banner && <Message kind={data.licence_banner.kind === 'licence_expired' ? 'error' : 'warning'}>{tx(data.licence_banner.text)}</Message>}
      <section aria-label={t('alerts')}>
        <Slot name="dashboard.alerts" />
        {data.alerts.map((a, i) => (
          <Message key={i} kind={a.severity === 'critical' ? 'error' : a.severity === 'info' ? 'info' : 'warning'}>
            {tx(a.text)} {a.link && <Link to={a.link}>→</Link>}
          </Message>
        ))}
      </section>
      {data.remote && <RemoteStrip remote={data.remote} companyId={companyId} onChange={reload} />}
      <section aria-labelledby="status-cards-title" style={{ margin: '16px 0' }}>
        <h2 id="status-cards-title">{t('status_cards')}</h2>
        <div className="grid">
          {CARD_TYPES.map((type) => <StatusCard key={type} type={type} items={items} shared={deadlines?.freshness_state !== 'not_shared'} />)}
        </div>
        <div className="grid" style={{ marginTop: 8 }}>
          <div className="card"><div className="stat-label">{t('k10_label')}</div><div>{tx(data.k10_tile)}</div></div>
        </div>
      </section>
      <NextSteps d={data} />
      {data.not_shared_note && <Message kind="info">{tx(data.not_shared_note)}</Message>}
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
        {data.panels.map((p) => <PanelBox key={p.panel} p={p} reload={reload} canPrepare={can('compliance.prepare', companyId)} canApprove={can('compliance.approve', companyId)} isOwner={data.acting_as.company_role === 'owner'} />)}
      </div>
      <div style={{ marginTop: 16 }}>
        <Slot name="dashboard.panels" />
      </div>
    </div>
  )
}

function ActingAs({ d }: { d: DashboardData }) {
  const { t } = useTranslation('dashboard')
  const [open, setOpen] = useState(false)
  const a = d.acting_as
  return (
    <div>
      <button className="acting-as" aria-expanded={open} aria-label={a.accessible_name} onClick={() => setOpen(!open)} style={{ minHeight: 44, border: '1px solid var(--border)', borderRadius: 999, padding: '0 14px', background: 'var(--surface)', cursor: 'pointer' }}>
        {a.role === 'owner' ? t('acting_owner') : t('acting_delegate', { owner: a.principal ?? '-' })} · {a.person}
        {a.owner_abroad && <> · <span aria-hidden="true">🌐</span> {t('owner_abroad')}</>}
      </button>
      {open && (
        <div className="card" style={{ marginTop: 6 }}>
          <strong>{t('held_functions')}</strong>
          <p>{a.held_functions.join(', ')}</p>
          {a.owner_only_functions.length > 0 && (
            <>
              <strong>{t('owner_only')}</strong>
              <ul>{a.owner_only_functions.map((f) => <li key={f}>{t(`owner_only_list.${f}`)}</li>)}</ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function StatusCard({ type, items, shared }: { type: (typeof CARD_TYPES)[number]; items: MiniObligation[]; shared: boolean }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const o = items.filter((x) => x.obligation_type === type).sort((a, b) => (a.days_left ?? 99999) - (b.days_left ?? 99999))[0]
  if (!shared) return null
  if (!o) {
    return (
      <div className="card"><h3 style={{ marginTop: 0 }}>{t(`card_type.${type}`)}</h3><p className="helper">{t('no_card')}</p></div>
    )
  }
  const tt = tierTone(o.days_left_tier)
  return (
    <div className="card" aria-label={`${tx(o.name)}, ${o.due_date ? formatDate(o.due_date, i18n.language) : ''}, ${o.days_left !== null ? daysLeftLabel(o.days_left, i18n.language) : ''}, ${t('missing_n', { n: o.missing_items.length })}`}>
      <h3 style={{ marginTop: 0 }}>{t(`card_type.${type}`)}</h3>
      {o.due_date ? <p style={{ margin: '4px 0' }}>{t('due', { date: formatDate(o.due_date, i18n.language) })}</p> : <p><Chip tone="info" icon="?">{t('date_not_confirmed')}</Chip></p>}
      {o.days_left !== null && <Chip tone={tt.tone} icon={tt.icon}>{daysLeftLabel(o.days_left, i18n.language)}</Chip>}
      <p style={{ margin: '6px 0' }}>
        {o.missing_items.length ? <Chip tone="attention" icon="!">{t('missing')}</Chip> : o.readiness === 'draft_ready' || o.readiness === 'owner_approved' ? <Chip tone="ok" icon="✓">{t('prepared')}</Chip> : null}{' '}
        <span className="helper">{tx(o.readiness_label)}</span>
      </p>
      {o.missing_items.length > 0 && <ul className="helper" style={{ margin: 0, paddingInlineStart: 18 }}>{o.missing_items.map((m) => <li key={m.code}>{i18n.language.startsWith('ar') ? m.label_ar : m.label_en}</li>)}</ul>}
      {o.is_demo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}
    </div>
  )
}

function NextSteps({ d }: { d: DashboardData }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  return (
    <Panel title={t('next_steps')}>
      {d.next_steps.length === 0 ? <p>{t('no_next_steps')}</p> : (
        <ol style={{ margin: 0, paddingInlineStart: 20 }}>
          {d.next_steps.map((s, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              {s.link ? <Link to={s.link}>{tx(s.title)}</Link> : tx(s.title)}
              {s.due_date && <span className="helper"> · {formatDate(s.due_date, i18n.language)}</span>}
              {s.ai_prepared && <> <AiLabel status={s.status_label ? tx(s.status_label) : undefined} /></>}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}

function PanelBox({ p, reload, canPrepare, canApprove, isOwner }: { p: PanelData; reload: () => void; canPrepare: boolean; canApprove: boolean; isOwner: boolean }) {
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
      <Panel title={<><span aria-hidden="true">🔒 </span>{title}</>} id={`panel-${p.panel}`}>
        <p>{t('not_shared')}</p>
        {sent ? (
          <Button variant="secondary" aria-disabled="true" disabled>{t('request_sent', { date: formatDate(sent, i18n.language) })}</Button>
        ) : (
          <Button variant="secondary" onClick={request}>{t('request_access')}</Button>
        )}
      </Panel>
    )
  }
  const freshTone = p.freshness_state === 'fresh' ? 'ok' : p.freshness_state === 'last_known' ? 'attention' : p.freshness_state === 'not_linked_yet' ? 'neutral' : 'critical'
  const header = (
    <p className="helper" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', margin: '0 0 8px' }}>
      <Chip tone={freshTone} icon={p.freshness_state === 'fresh' ? '✓' : p.freshness_state === 'last_known' ? '◷' : '!'}>{t(`freshness.${p.freshness_state}`)}</Chip>
      {p.source && <span>{t('source', { source: p.source })}</span>}
      {p.last_updated && <span>· {t('last_updated', { time: formatDateTime(p.last_updated, i18n.language) })}</span>}
    </p>
  )
  if (p.freshness_state === 'not_available' || p.freshness_state === 'could_not_be_loaded') {
    return (
      <Panel title={title} id={`panel-${p.panel}`}>
        {header}
        <Message kind="error">
          {p.panel === 'deadlines' ? t('error_deadlines') : tx(p.message)} {p.reason_code === 'SOURCE_TIMEOUT_NO_CACHE' && <span className="helper">({t('timeout_reason')} <Ident>{p.reason_code}</Ident>)</span>}
        </Message>
        <Button variant="secondary" onClick={reload}>{t('retry')}</Button>
      </Panel>
    )
  }
  return (
    <Panel title={title} id={`panel-${p.panel}`}>
      {header}
      {p.freshness_state === 'cannot_be_confirmed' && <Message kind="warning">{tx(p.message)} · {t('stale_note', { time: formatDateTime(p.last_good_time, i18n.language) })}</Message>}
      {p.freshness_state === 'not_linked_yet' && <p><strong>{t('not_linked_yet')}</strong></p>}
      {p.data && <PanelBody p={p} reload={reload} canPrepare={canPrepare} canApprove={canApprove} isOwner={isOwner} />}
    </Panel>
  )
}

function PanelBody({ p, reload, canPrepare, canApprove, isOwner }: { p: PanelData; reload: () => void; canPrepare: boolean; canApprove: boolean; isOwner: boolean }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const d = p.data
  switch (p.panel) {
    case 'tax_status':
      return (
        <div>
          {d.lines?.map((l: { en: string; ar: string }, i: number) => <p key={i} style={{ margin: '4px 0' }}>{tx(l)} <Chip tone="info" icon="?">{t('unconfirmed')}</Chip></p>)}
          {d.next_step && <p><Link to="/deadlines">{tx(d.next_step)}</Link></p>}
          <MiniList items={d.deadlines ?? []} />
          {d.sbr && <p className="helper"><strong>{t('sbr_title')}: </strong>{tx(d.sbr.text)}</p>}
          {d.audit_required_line && <p className="helper">{tx(d.audit_required_line)}</p>}
          <p className="helper">{t('k10_label')}: {tx(d.k10)}</p>
        </div>
      )
    case 'audit_status':
      return (
        <div>
          <p><Chip tone="info" icon="○">{d.state_label ? tx(d.state_label) : t('audit_not_assessed')}</Chip></p>
          {d.reason && <p>{typeof d.reason === 'string' ? d.reason : tx(d.reason)}</p>}
          <p className="helper">{d.last_updated_label ? tx(d.last_updated_label) : ''}</p>
          <p className="helper">{t('audit_note')}</p>
        </div>
      )
    case 'deadlines':
      return (
        <div>
          <MiniList items={d.items ?? []} />
          {d.withheld_note && <p className="helper">{tx(d.withheld_note)}</p>}
          <Link to="/deadlines">{t('open_deadlines')}</Link>
        </div>
      )
    case 'documents':
      return (
        <div>
          {(d.items ?? []).length === 0 ? <Empty title={t('documents_empty')} /> : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {d.items.map((x: { document_id: string; title: string; title_ar: string; review_label: { en: string; ar: string }; link: string | null; is_demo: boolean }) => (
                <li key={x.document_id} style={{ marginBottom: 8 }}>
                  {x.link ? <Link to={x.link}>{i18n.language.startsWith('ar') ? x.title_ar : x.title}</Link> : <span>{i18n.language.startsWith('ar') ? x.title_ar : x.title}</span>}{' '}
                  <AiLabel status={tx(x.review_label)} /> {x.is_demo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}
                </li>
              ))}
            </ul>
          )}
          <p className="helper">{t('k28_label')}: {tx(d.k28)}</p>
        </div>
      )
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
    <ul style={{ listStyle: 'none', padding: 0, margin: '6px 0' }}>
      {items.slice(0, 6).map((o) => {
        const tt = tierTone(o.days_left_tier)
        return (
          <li key={o.obligation_id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
            <span>{tx(o.name)}{o.calculated && o.due_date ? <span className="helper"> · {t('calculated')}</span> : null}</span>
            <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
              {o.due_date ? <span>{t('due', { date: formatDate(o.due_date, i18n.language) })}</span> : <Chip tone="info" icon="?">{t('date_not_confirmed')}</Chip>}
              {o.days_left !== null && <Chip tone={tt.tone} icon={tt.icon}>{daysLeftLabel(o.days_left, i18n.language)}</Chip>}
              {o.missing_items.length > 0 ? <Chip tone="attention" icon="!">{t('missing')}</Chip> : o.readiness === 'draft_ready' ? <Chip tone="ok" icon="✓">{t('prepared')}</Chip> : null}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
