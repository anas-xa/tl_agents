import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Empty, Field, Ident, Message, Panel, Skeleton, StatCard, Table } from '../../components/ui'
import { MetaLine, SectionHead } from '../det/ui'
import { ApiError, get } from '../../lib/api'
import { formatDateTime, formatNumber } from '../../lib/format'

type Cell = { suppressed: true; fewer_than: number } | { suppressed: false; total?: number; escalated?: number; events?: number; rate_per_100?: number | null; note?: string; resolved?: number; active_working_days?: number | null; raw_working_days?: number | null; first_response_working_days?: number | null; no_data?: boolean }
type Count = number | { suppressed: true; fewer_than: number }
interface Agg {
  period: { from: string; to: string; months: string[] }
  suppression: { min_group_size: number }
  k21: { headline: Cell; by_module: Record<string, Cell>; by_reason: Record<string, Cell>; mandatory_vs_discretionary: Record<string, Cell>; legal_separate: Record<string, Cell> }
  k22: { headline: Cell; by_module: Record<string, Cell>; by_role_label: Record<string, Cell>; by_priority: Record<string, Cell>; withdrawn_count: Count; closed_no_consent_count: Count; outcome_c_count: Count; open: { count: Count; age_bands: Record<string, Cell> } }
  data_quality: { counter: number }
  calendar: { version: string; missing: boolean; provisional: boolean }
  refresh: { last_refreshed_at: string; stale: boolean }
  empty: boolean
}

/** SC14 'Escalations' tab: K21/K22 aggregate tiles with suppression, five filters, no drill-down. */
export default function EscalationsTab() {
  const { t, i18n } = useTranslation('cases')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const today = new Date()
  const from0 = new Date(today.getTime() - 89 * 86400000)
  const [f, setF] = useState({ period_from: from0.toISOString().slice(0, 10), period_to: today.toISOString().slice(0, 10), module: '', reason: '', specialist_type: '', priority: '' })
  const [agg, setAgg] = useState<Agg | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(() => {
    setLoading(true)
    const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][])
    get<Agg>(`/api/det/escalations?${p.toString()}`).then((a) => { setAgg(a); setErr(null) }).catch((e: ApiError) => setErr(e.code)).finally(() => setLoading(false))
  }, [f])
  useEffect(() => { load() }, [load])
  const n = agg?.suppression.min_group_size ?? 10
  const fewer = (c: Cell) => <Chip tone="neutral" icon="▭" title={t('dashboard.fewer', { n: c.suppressed ? c.fewer_than : n })}>{t('dashboard.fewer_short', { n: c.suppressed ? c.fewer_than : n })}</Chip>
  const num = (v: number | null | undefined, frac = 1) => (v === null || v === undefined ? t('dashboard.no_data') : <Ident>{formatNumber(v, lang, frac)}</Ident>)
  const count = (c: Count) => (typeof c === 'number' ? <Ident>{formatNumber(c, lang)}</Ident> : fewer(c))
  const k21Cell = (c: Cell) => (c.suppressed ? fewer(c) : c.note === 'not_applicable' ? t('dashboard.not_applicable') : num(c.rate_per_100))
  const k22Cell = (c: Cell) => (c.suppressed ? fewer(c) : c.no_data || c.active_working_days === null ? t('dashboard.no_data') : <>{num(c.active_working_days)} / {num(c.raw_working_days)}</>)
  const label = (k: string) => (t(`dashboard.modules.${k}`, { defaultValue: '' }) || t(`dashboard.groups.${k}`, { defaultValue: '' }) || t(`reason.${k}`, { defaultValue: '' }) || t(`priority.${k}`, { defaultValue: '' }) || (k === 'unclassified' ? t('dashboard.unclassified') : k === 'other' ? t('dashboard.other') : k === 'total' ? t('dashboard.modules.total') : k))
  const breakdown = (title: string, cells: Record<string, Cell>, kind: 'k21' | 'k22') => {
    const keys = Object.keys(cells).filter((k) => k !== 'total').concat(Object.keys(cells).includes('total') ? ['total'] : [])
    const val = (c: Cell) => (c.suppressed ? 0 : kind === 'k21' ? c.rate_per_100 ?? 0 : c.active_working_days ?? 0)
    const max = Math.max(1, ...keys.map((k) => val(cells[k])))
    return (
      <Panel title={title} key={title} className="det-panel-flush">
        <div className="table-compact det-table">
        <Table headers={kind === 'k21' ? [t('dashboard.cols.group'), t('dashboard.cols.total'), t('dashboard.cols.escalated'), t('dashboard.cols.events'), t('dashboard.cols.rate')] : [t('dashboard.cols.group'), t('dashboard.cols.escalated'), t('dashboard.cols.resolved'), t('dashboard.cols.active'), t('dashboard.cols.raw'), t('dashboard.cols.first')]}>
          {keys.map((k) => { const c = cells[k]; const bar = !c.suppressed && <span className="det-bar" aria-hidden="true"><span style={{ inlineSize: `${(val(c) / max) * 100}%` }} /></span>; return (
            <tr key={k} className={k === 'total' ? 'det-row-total' : undefined}>
              <td>{label(k)}</td>
              {kind === 'k21' ? (c.suppressed ? <td colSpan={4}>{fewer(c)}</td> : <><td className="num">{num(c.total, 0)}</td><td className="num">{num(c.escalated, 0)}</td><td className="num">{num(c.events, 0)}</td><td className="num det-bar-cell">{k21Cell(c)}{bar}</td></>) : (c.suppressed ? <td colSpan={5}>{fewer(c)}</td> : <><td className="num">{num(c.escalated, 0)}</td><td className="num">{num(c.resolved, 0)}</td><td className="num det-bar-cell">{num(c.active_working_days)}{bar}</td><td className="num">{num(c.raw_working_days)}</td><td className="num">{num(c.first_response_working_days)}</td></>)}
            </tr>
          ) })}
        </Table>
        </div>
      </Panel>
    )
  }
  return (
    <div className="escalations-tab">
      <SectionHead first title={t('dashboard.title')} hint={`${t('dashboard.aggregate')} ${t('dashboard.no_drill')} ${t('dashboard.no_target')}`} />
      <form className="toolbar det-toolbar" role="search" aria-label={t('dashboard.filters.apply')} onSubmit={(e) => { e.preventDefault(); load() }}>
        <Field label={t('dashboard.filters.period_from')} id="pf"><input id="pf" type="date" value={f.period_from} onChange={(e) => setF({ ...f, period_from: e.target.value })} /></Field>
        <Field label={t('dashboard.filters.period_to')} id="pt"><input id="pt" type="date" value={f.period_to} onChange={(e) => setF({ ...f, period_to: e.target.value })} /></Field>
        <Field label={t('dashboard.filters.module')} id="fm"><select id="fm" value={f.module} onChange={(e) => setF({ ...f, module: e.target.value })}><option value="">{t('dashboard.filters.all')}</option>{['tax', 'audit', 'compliance', 'legal'].map((m) => <option key={m} value={m}>{t(`dashboard.modules.${m}`)}</option>)}</select></Field>
        <Field label={t('dashboard.filters.reason')} id="fr"><select id="fr" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })}><option value="">{t('dashboard.filters.all')}</option>{['complex_tax', 'audit_signoff_required', 'legal_matter', 'low_confidence', 'user_requested', 'data_conflict', 'deadline_risk'].map((r) => <option key={r} value={r}>{t(`reason.${r}`, { defaultValue: r })}</option>)}</select></Field>
        <Field label={t('dashboard.filters.specialist_type')} id="fs"><select id="fs" value={f.specialist_type} onChange={(e) => setF({ ...f, specialist_type: e.target.value })}><option value="">{t('dashboard.filters.all')}</option>{['tax', 'auditor', 'lawyer', 'compliance'].map((s) => <option key={s} value={s}>{t(`specialist.${s}`, { defaultValue: s })}</option>)}</select></Field>
        <Field label={t('dashboard.filters.priority')} id="fp" hint={t('dashboard.filters.na')}><select id="fp" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}><option value="">{t('dashboard.filters.all')}</option><option value="standard">{t('priority.standard')}</option><option value="deadline_near">{t('priority.deadline_near')}</option></select></Field>
        <div className="toolbar-end"><Button type="submit" variant="secondary">{t('dashboard.filters.apply')}</Button></div>
      </form>
      {err && <Message kind="error">{err === 'NO_PERMISSION' ? t('dashboard.no_access') : t('dashboard.error')} <Button variant="link" onClick={load}>{t('dashboard.filters.apply')}</Button></Message>}
      {loading && !agg && <Skeleton rows={4} />}
      {agg && (
        <>
          <div className="stat-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))' }}>
            <StatCard className="det-esc-stat" icon="activity" label={<>{t('dashboard.k21')}</>} value={<span id="k21">{agg.empty ? '—' : k21Cell(agg.k21.headline)}</span>} hint={t('dashboard.k21_def')} />
            <StatCard className="det-esc-stat" icon="clock" label={<>{t('dashboard.k22')}</>} value={<span id="k22">{agg.empty ? '—' : k22Cell(agg.k22.headline)}</span>}
              hint={<>{!agg.k22.headline.suppressed && agg.k22.headline.first_response_working_days != null && <>{t('dashboard.first_response')}: {num(agg.k22.headline.first_response_working_days)} · </>}{t('dashboard.open_not_counted')}<br />{t('dashboard.k22_def')}</>} />
          </div>
          <p className="det-note">
            <MetaLine items={[
              t('dashboard.refreshed', { date: formatDateTime(agg.refresh.last_refreshed_at, lang) }),
              agg.refresh.stale ? <Chip key="st" tone="attention" icon="!">{t('dashboard.stale')}</Chip> : null,
              t('dashboard.month', { months: agg.period.months.join(', ') }),
              t('dashboard.calendar', { version: agg.calendar.version }),
              agg.calendar.provisional ? <Chip key="pr" tone="attention" icon="◔">{t('dashboard.provisional')}</Chip> : null,
              agg.calendar.missing ? <Chip key="cm" tone="urgent" icon="!">{t('dashboard.calendar_missing')}</Chip> : null,
              <Chip key="dq" tone={agg.data_quality.counter ? 'attention' : 'neutral'} icon="≠">{t('dashboard.data_quality', { n: agg.data_quality.counter })}</Chip>,
            ]} />
          </p>
          {agg.empty ? <Empty icon="activity" title={t('dashboard.empty')} /> : (
            <>
            <SectionHead level={3} title={t('dashboard.k21')} />
            <div className="det-two">
              {breakdown(t('dashboard.sections.by_module') + ' · K21', agg.k21.by_module, 'k21')}
              {breakdown(t('dashboard.sections.by_reason'), agg.k21.by_reason, 'k21')}
              {breakdown(t('dashboard.sections.mandatory'), agg.k21.mandatory_vs_discretionary, 'k21')}
              {breakdown(t('dashboard.modules.legal'), agg.k21.legal_separate, 'k21')}
            </div>
            <SectionHead level={3} title={t('dashboard.k22')} />
            <div className="det-stack">
              {breakdown(t('dashboard.sections.by_module') + ' · K22', agg.k22.by_module, 'k22')}
              {breakdown(t('dashboard.sections.by_role'), agg.k22.by_role_label, 'k22')}
              {breakdown(t('dashboard.sections.by_priority'), agg.k22.by_priority, 'k22')}
            </div>
            <div className="det-two" style={{ marginTop: 20 }}>
              <Panel title={t('dashboard.sections.open')} className="det-panel-flush" actions={<span className="det-big" style={{ fontSize: 'var(--fs-xl)' }}>{count(agg.k22.open.count)}</span>}>
                <div className="table-compact det-table">
                <Table headers={[t('dashboard.cols.group'), t('dashboard.cols.escalated')]}>
                  {Object.entries(agg.k22.open.age_bands).map(([k, c]) => <tr key={k} className={k === 'total' ? 'det-row-total' : undefined}><td className="nowrap">{k === 'total' ? t('dashboard.modules.total') : <bdi dir="ltr">{k}</bdi>}</td><td className="num">{c.suppressed ? fewer(c) : num(c.escalated, 0)}</td></tr>)}
                </Table>
                </div>
              </Panel>
              <Panel title={t('dashboard.sections.counts')}>
                <dl className="det-kpi-kv">
                  <dt>{t('dashboard.counts.withdrawn')}</dt><dd>{count(agg.k22.withdrawn_count)}</dd>
                  <dt>{t('dashboard.counts.closed_no_consent')}</dt><dd>{count(agg.k22.closed_no_consent_count)}</dd>
                  <dt>{t('dashboard.counts.outcome_c')}</dt><dd>{count(agg.k22.outcome_c_count)}</dd>
                </dl>
              </Panel>
            </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
