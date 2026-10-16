import { Fragment, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Empty, Field, Message, PageHeader, Panel, Skeleton, Toolbar } from '../../components/ui'
import { ApiError, post } from '../../lib/api'
import { digits, formatDate } from '../../lib/format'
import CalendarView from './CalendarView'
import { errorCode, srOnly, useBi, useFetch, type CompanyView, type Obligation, type PortfolioView } from './lib'
import { DateUpdatedChip, DaysBadge, MissingList, ObligationDetail, ReadinessChip, ShownDate, SourceLine, StatusChips } from './parts'
import './deadlines.css'

const VIEW_KEY = 'qx_deadlines_view'
const TYPES = ['vat_return', 'ct_return', 'licence_renewal', 'ejari_renewal', 'other'] as const

function readView(): 'list' | 'calendar' {
  try {
    return localStorage.getItem(VIEW_KEY) === 'calendar' ? 'calendar' : 'list'
  } catch {
    return 'list'
  }
}

/** SC4 Deadline calendar and list: every company the user may see, flat list soonest first, overdue pinned top. */
export default function Deadlines() {
  const { t, i18n } = useTranslation('deadlines')
  const { lang } = useBi()
  const { me, companyId, can } = useAuth()
  const [view, setView] = useState<'list' | 'calendar'>(readView)
  const [company, setCompany] = useState('')
  const [type, setType] = useState('')
  const [status, setStatus] = useState<'open' | 'done'>('open')
  const [openId, setOpenId] = useState<string | null>(null)
  const [announce, setAnnounce] = useState('')
  const all = useFetch<PortfolioView>('/api/me/obligations?include_done=true')
  const current = useFetch<CompanyView>(companyId && can('deadlines.view', companyId) ? `/api/companies/${companyId}/obligations` : null)
  const toggleRef = useRef<HTMLDivElement>(null)

  const setV = (v: 'list' | 'calendar') => {
    setView(v)
    setAnnounce(v === 'list' ? t('list_selected') : t('calendar_selected'))
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      /* per-viewer convenience only */
    }
  }
  const rows = useMemo(() => {
    const items = all.data?.items ?? []
    return items.filter((o) => (!company || o.company_id === company) && (!type || o.obligation_type === type) && (status === 'done' ? o.done : !o.done))
  }, [all.data, company, type, status])

  if (!me) return null
  if (all.error && errorCode(all.error) === 'NO_PERMISSION') return <Message kind="error">{t('no_access')}</Message>
  const companies = all.data?.companies ?? []
  const pendingN = rows.filter((r) => r.recalc_state === 'recalculation_pending').length
  const onToggleKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    setV(view === 'list' ? 'calendar' : 'list')
    const btns = toggleRef.current?.querySelectorAll('button')
    btns?.[view === 'list' ? 1 : 0]?.focus()
  }
  const groups = groupRows(rows)
  return (
    <div className="dl-page">
      <PageHeader
        title={t('title')}
        subtitle={t('intro')}
        meta={current.data?.rules_version ? <span className="dln-meta"><Icon name="file-check" size={16} />{t('rules_version', { v: current.data.rules_version.version, date: formatDate(current.data.rules_version.checked, i18n.language) })}</span> : undefined}
        actions={
          <div ref={toggleRef} role="group" aria-label={t('view_group')} className="dln-seg" onKeyDown={onToggleKey}>
            <button type="button" aria-pressed={view === 'list'} onClick={() => setV('list')}><Icon name="menu" size={18} />{t('view_list')}</button>
            <button type="button" aria-pressed={view === 'calendar'} onClick={() => setV('calendar')}><Icon name="calendar" size={18} />{t('view_calendar')}</button>
          </div>
        }
      />
      <div aria-live="polite" style={srOnly}>{announce}{pendingN ? ` ${t('updating_n', { n: pendingN })}` : ''}</div>
      <Toolbar label={t('filters')}>
        <Field label={t('filter_company')} id="dl-company">
          <select id="dl-company" value={company} onChange={(e) => setCompany(e.target.value)}>
            <option value="">{t('filter_all_companies')}</option>
            {companies.map((c) => <option key={c.company_id} value={c.company_id}>{lang === 'ar' ? c.trade_name_ar : c.trade_name_en}</option>)}
          </select>
        </Field>
        <Field label={t('filter_type')} id="dl-type">
          <select id="dl-type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">{t('filter_all_types')}</option>
            {TYPES.map((x) => <option key={x} value={x}>{t(`type.${x}`)}</option>)}
          </select>
        </Field>
        <Field label={t('filter_status')} id="dl-status">
          <select id="dl-status" value={status} onChange={(e) => setStatus(e.target.value as 'open' | 'done')}>
            <option value="open">{t('filter_open')}</option>
            <option value="done">{t('filter_done')}</option>
          </select>
        </Field>
      </Toolbar>
      {current.data?.pending && <Message kind="info">{t('pending')}</Message>}
      {all.data?.withheld_note && <Message kind="info">{t('withheld')}</Message>}
      {all.loading && !all.data && (
        <Panel>
          <p aria-busy="true">{t('loading')}</p>
          <Skeleton rows={5} />
        </Panel>
      )}
      {all.error && !all.data && (
        <Message kind="error">
          {t('error')} <Button variant="link" onClick={all.reload}>{t('try_again')}</Button>
        </Message>
      )}
      {all.data && current.data?.empty_state && <TaxDetailsEmpty view={current.data} onSaved={() => { all.reload(); current.reload() }} />}
      {all.data && rows.length === 0 && (all.data.items.length > 0 ? (
        <Empty icon="search" title={t('no_match')} action={<Button variant="secondary" onClick={() => { setCompany(''); setType(''); setStatus('open') }}>{t('clear_filters')}</Button>} />
      ) : !current.data?.empty_state ? <Empty icon="calendar" title={t('empty_title')} body={t('empty_linked')} /> : null)}
      {all.data && rows.length > 0 && view === 'list' && (
        <div className="dln-groups">
          {groups.map((g) => (
            <section key={g.key} className={`dln-group dln-group-${g.key}`} aria-labelledby={`dln-${g.key}`}>
              <h2 id={`dln-${g.key}`} className="dln-group-title">
                <span className="dln-group-icon" aria-hidden="true"><Icon name={g.key === 'overdue' ? 'alert' : g.key === 'soon' ? 'clock' : g.key === 'done' ? 'check' : 'calendar'} size={16} /></span>
                {t(`group.${g.key}`)}
                <span className="tab-badge">{g.rows.length}</span>
              </h2>
              <ul className="dln-list" aria-label={t(`group.${g.key}`)}>
                {g.rows.map((o) => (
                  <Fragment key={o.obligation_id}>
                    <DeadlineRow o={o} open={openId === o.obligation_id} onToggle={() => setOpenId(openId === o.obligation_id ? null : o.obligation_id)} />
                  </Fragment>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      {all.data && view === 'calendar' && <div className="card dln-cal"><CalendarView rows={rows} companyId={companyId} onOpen={(id) => { setV('list'); setOpenId(id) }} /></div>}
      {all.data && current.data?.empty_state && <p className="helper">{t('incomplete_note')}</p>}
    </div>
  )
}

type GroupKey = 'overdue' | 'soon' | 'later' | 'undated' | 'done'

/** Urgency groups for the list (order kept from the API within each group: soonest first). */
function groupRows(rows: Obligation[]): { key: GroupKey; rows: Obligation[] }[] {
  const out: Record<GroupKey, Obligation[]> = { overdue: [], soon: [], later: [], undated: [], done: [] }
  for (const o of rows) {
    if (o.done) out.done.push(o)
    else if (o.days_left === null || o.due_date === null) out.undated.push(o)
    else if (o.days_left < 0) out.overdue.push(o)
    else if (o.days_left <= 30) out.soon.push(o)
    else out.later.push(o)
  }
  return (['overdue', 'soon', 'later', 'undated', 'done'] as GroupKey[]).filter((k) => out[k].length).map((key) => ({ key, rows: out[key] }))
}

function DateBlock({ o }: { o: Obligation }) {
  const { lang } = useBi()
  if (!o.due_date) return <span className="dln-date is-undated" aria-hidden="true">?</span>
  const d = new Date(o.due_date + 'T00:00:00')
  let month = ''
  try {
    month = new Intl.DateTimeFormat(lang === 'ar' ? 'ar-AE' : 'en-GB', { month: 'short' }).format(d)
  } catch {
    month = o.due_date.slice(5, 7)
  }
  return (
    <span className={`dln-date tier-${o.done ? 'done' : o.days_left_tier}`} aria-hidden="true">
      <span className="dln-date-day">{digits(String(d.getDate()), lang)}</span>
      <span className="dln-date-month">{month}</span>
      <span className="dln-date-year">{digits(String(d.getFullYear()), lang)}</span>
    </span>
  )
}

function SourceChip({ o }: { o: Obligation }) {
  const { t } = useTranslation('deadlines')
  return <Chip tone="info" icon={o.is_stated ? '⚑' : '∑'}>{o.is_stated ? t('source_stated') : t('source_computed')}</Chip>
}

function DeadlineRow({ o, open, onToggle }: { o: Obligation; open: boolean; onToggle: () => void }) {
  const { t, i18n } = useTranslation('deadlines')
  const { tx } = useBi()
  const days = o.days_left === null ? t('undated') : o.done ? '' : o.days_left
  const accessible = t('accessible_row', { name: tx(o.name), date: o.due_date ? formatDate(o.due_date, i18n.language) : t('undated'), days: String(days), missing: o.missing_items.length })
  const detailId = `dln-detail-${o.obligation_id}`
  return (
    <li className={`dln-row ${open ? 'is-open' : ''}`} aria-label={accessible}>
      <div className="dln-row-main">
        <DateBlock o={o} />
        <div className="dln-body">
          <div className="dln-title">
            <strong>{tx(o.name)}</strong>
            <span className="dln-company"><bdi>{tx(o.company_name)}</bdi></span>
          </div>
          <div className="dln-sub">
            <ShownDate o={o} />
            {o.period_start && <span>{t('period', { start: formatDate(o.period_start, i18n.language), end: formatDate(o.period_end, i18n.language) })}</span>}
          </div>
          <div className="dln-chips">
            <DaysBadge o={o} />
            <StatusChips o={o} />
            <ReadinessChip o={o} />
            <SourceChip o={o} />
            {o.is_demo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}
          </div>
          {o.missing_items.length > 0 && <MissingList o={o} />}
          {o.recalc_state === 'recalculation_pending' && <p className="helper">{t('pending_note')}</p>}
          {o.recalc_state === 'recalculation_failed' && o.last_confirmed_date && <Message kind="warning">{t('error_rule', { date: formatDate(o.last_confirmed_date, i18n.language), saved: formatDate(o.calculation_time, i18n.language) })}</Message>}
          <DateUpdatedChip o={o} />
        </div>
        <div className="dln-action">
          <Button variant="secondary" className="btn-sm" aria-expanded={open} aria-controls={detailId} onClick={onToggle}>
            {open ? t('close_detail') : t('open_detail')}<Icon name="chevron-down" size={16} className="dln-chevron" />
          </Button>
        </div>
      </div>
      {open && (
        <div className="dln-detail" id={detailId}>
          <SourceLine o={o} />
          {o.calculated && o.due_date && !o.notes.some((n) => tx(n) === t('calculated_note')) && <p className="helper">{t('calculated_note')}</p>}
          {o.notes.length > 0 && <ul className="helper dln-notes">{o.notes.map((n, i) => <li key={i}>{tx(n)}</li>)}</ul>}
          <ObligationDetail o={o} />
        </div>
      )}
    </li>
  )
}

/** Empty state with inline fields (owner / delegate with the function) or 'Ask the owner' + 'Notify owner'. */
function TaxDetailsEmpty({ view, onSaved }: { view: CompanyView; onSaved: () => void }) {
  const { t } = useTranslation('deadlines')
  const { companyId } = useAuth()
  const es = view.empty_state!
  const [form, setForm] = useState({ tax_period_start: '', tax_period_end: '', filing_frequency: 'quarterly', trn: '', no_trn: false })
  const [msg, setMsg] = useState<{ kind: 'success' | 'error' | 'info'; text: string } | null>(null)
  const isOwner = view.role === 'owner' || view.role === 'remote_owner'
  const save = async () => {
    try {
      await post(`/api/companies/${companyId}/obligations/tax-details`, { tax_type: 'vat', tax_period_start: form.tax_period_start || null, tax_period_end: form.tax_period_end || null, filing_frequency: form.filing_frequency, trn: form.no_trn ? null : form.trn || null })
      setMsg({ kind: 'success', text: t('saved') })
      onSaved()
    } catch (e) {
      setMsg({ kind: 'error', text: (e as Error).message })
    }
  }
  const notify = async (code: string) => {
    try {
      await post(`/api/companies/${companyId}/obligations/notify-owner`, { item_code: code })
      setMsg({ kind: 'success', text: t('notified') })
    } catch (e) {
      setMsg({ kind: 'info', text: e instanceof ApiError && e.code === 'NOTIFY_RATE_LIMITED' ? t('notify_limited') : (e as Error).message })
    }
  }
  return (
    <Panel title={t('empty_title')}>
      <p>{isOwner ? t('empty_owner') : t('empty_delegate')}</p>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      {es.fields.length > 0 ? (
        <div>
          {isOwner && <p className="helper">{t('owner_text')} · {t('owner_entered')}</p>}
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
            <Field label={t('tax_period_start')} id="td-start" hint={t('owner_entered')}><input id="td-start" type="date" value={form.tax_period_start} onChange={(e) => setForm({ ...form, tax_period_start: e.target.value })} /></Field>
            <Field label={t('tax_period_end')} id="td-end"><input id="td-end" type="date" value={form.tax_period_end} onChange={(e) => setForm({ ...form, tax_period_end: e.target.value })} /></Field>
            <Field label={t('vat_frequency')} id="td-freq">
              <select id="td-freq" value={form.filing_frequency} onChange={(e) => setForm({ ...form, filing_frequency: e.target.value })}>
                {(['monthly', 'quarterly', 'annual'] as const).map((f) => <option key={f} value={f}>{t(`freq.${f}`)}</option>)}
              </select>
            </Field>
            <Field label={t('trn')} id="td-trn">
              <input id="td-trn" inputMode="numeric" dir="ltr" maxLength={15} value={form.trn} disabled={form.no_trn} onChange={(e) => setForm({ ...form, trn: e.target.value.replace(/\D/g, '') })} />
              <label style={{ display: 'flex', gap: 6, alignItems: 'center', minHeight: 44 }}><input type="checkbox" checked={form.no_trn} onChange={(e) => setForm({ ...form, no_trn: e.target.checked })} /> {t('no_trn_yet')}</label>
            </Field>
          </div>
          <Button onClick={save}>{t('add_tax_details')}</Button>
        </div>
      ) : (
        <div>
          <p>{t('ask_owner_add')}</p>
          <Button variant="secondary" onClick={() => notify('tax_details')}>{t('notify_owner')}</Button>
        </div>
      )}
    </Panel>
  )
}
