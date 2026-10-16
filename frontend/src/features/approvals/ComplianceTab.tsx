import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip, Empty, Field, Message, Panel, Skeleton, Table } from '../../components/ui'
import { get, post } from '../../lib/api'
import { formatDateTime, formatNumber } from '../../lib/format'
import { formatDubaiDate } from '../det/headerMeta'
import { MetaLine } from '../det/ui'
import { useLang } from './parts'
import type { ComplianceView } from './types'

/** SC14/SC15 'Approval compliance' (E6-S4): K23 pass/fail with breach count, K24, exceptions, blocked attempts.
 *  Read-only: references and codes only, no financial figures; read-back is 'Not available' in Phase 1. */
export default function ComplianceTab() {
  const { t } = useTranslation('approvals')
  const lang = useLang()
  const [data, setData] = useState<ComplianceView | null>(null)
  const [error, setError] = useState(false)
  const [slow, setSlow] = useState(false)
  const [filters, setFilters] = useState({ period: '', tax_type: '', approver_role: '' })
  const [asTable, setAsTable] = useState(false)

  const load = useCallback(async () => {
    setData(null)
    setSlow(false)
    const timer = setTimeout(() => setSlow(true), 10000)
    try {
      const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][])
      setData(await get<ComplianceView>(`/api/det/approval-compliance${q.toString() ? `?${q}` : ''}`))
      setError(false)
    } catch {
      setError(true)
    } finally {
      clearTimeout(timer)
    }
  }, [filters])
  useEffect(() => {
    load()
  }, [load])

  const retry = async () => {
    try {
      await post('/api/det/approval-compliance/run')
    } finally {
      load()
    }
  }

  if (error)
    return (
      <Message kind="error">
        {t('comp_error')} <Button variant="secondary" onClick={load}>{t('retry')}</Button>
      </Message>
    )
  if (!data)
    return (
      <div aria-live="polite">
        <p>{t('loading_comp', { time: '' })}</p>
        {slow && <p>{t('long_wait')}</p>}
        <Skeleton rows={4} />
      </div>
    )

  const k23 = data.k23
  const k24 = data.k24
  const stale = data.job.stale
  return (
    <div className="compliance-tab">
      <p className="det-note"><Icon name="lock" size={16} />{t('comp_readonly')}</p>
      {stale && (
        <div role="alert" className="message message-warning">
          <span aria-hidden="true" className="message-icon">!</span>
          <div>
            {t('stale', { when: data.job.last_success_at ? formatDateTime(data.job.last_success_at, lang) : '—' })}
            {data.can_retry && <> <Button variant="secondary" onClick={retry}>{data.job.last_success_at ? t('retry') : t('run_job')}</Button></>}
          </div>
        </div>
      )}
      {!data.flow_enabled && <Message kind="warning">{t('flow_status_off')}</Message>}
      {data.flow_enabled && data.wave_exit_blocked && <Message kind="warning">{t('wave_blocked')}</Message>}
      <div className="det-two" style={{ marginBottom: 20 }}>
        <section className="card det-kpi" id="k23" aria-labelledby="k23-title">
          <header className="det-kpi-head"><h3 id="k23-title" className="det-cap">{t('k23_name')}</h3><span className="det-kpi-code"><bdi dir="ltr">K23</bdi></span></header>
          {k23.status === 'no_data' ? (
            <>
              <p className="det-kpi-state" aria-label={t('k23_sr')}><Chip tone="neutral" icon="i">{t('no_data')}</Chip></p>
              <p className="det-kpi-target">{t('k23_no_data')}</p>
            </>
          ) : (
            <>
              <p className="det-kpi-value"><bdi dir="ltr">{formatNumber(k23.value_pct, lang, 1)}%</bdi></p>
              <div className="det-kpi-chips">
                {k23.status === 'breach' ? <Chip tone="urgent" icon="⚠">{t('breach_count', { n: k23.breach_count })}</Chip> : <Chip tone="ok">{t('k23_pass')}</Chip>}
                {stale && <Chip tone="attention">{t('stale_tag')}</Chip>}
              </div>
              {k23.status === 'breach' && <p className="det-kpi-target"><a href="#exceptions">{t('k23_breach', { x: k23.breach_count, y: k23.denominator })}</a></p>}
            </>
          )}
          {k23.status === 'no_data' && stale && <div className="det-kpi-chips"><Chip tone="attention">{t('stale_tag')}</Chip></div>}
          <p className="det-kpi-target">{t('k23_definition')}</p>
          <div className="det-kpi-foot" style={{ paddingBlock: 10 }}>
            <MetaLine items={[t('self_reported', { n: k23.self_reported_count }), t('releases', { n: k23.release_approvals }), t('blocked_attempts', { n: k23.blocked_attempts })]} />
          </div>
        </section>
        <section className="card det-kpi" id="k24" aria-labelledby="k24-title">
          <header className="det-kpi-head"><h3 id="k24-title" className="det-cap">{t('k24_name')}</h3><span className="det-kpi-code"><bdi dir="ltr">K24</bdi></span></header>
          {k24.mean_hours === null ? <p className="det-kpi-state">{t('k24_no_data')}</p> : <p className="det-kpi-value"><bdi dir="ltr">{formatNumber(k24.mean_hours, lang, 1)}</bdi></p>}
          <div className="det-kpi-chips">
            <Chip tone={k24.undecided_count ? 'attention' : 'neutral'} icon="◷">{t('k24_waiting', { n: k24.undecided_count })}</Chip>
            {stale && <Chip tone="attention">{t('stale_tag')}</Chip>}
          </div>
          {k24.target_hours === null && <p className="det-kpi-target">{t('k24_no_target')}</p>}
          {asTable ? (
            <div className="table-compact det-table">
            <Table headers={[t('filter_role'), t('avg_hours')]}>
              {Object.entries(k24.breakdown).map(([k, v]) => (
                <tr key={k}><td>{t(`k24_bd_${k}`)}</td><td className="num"><bdi dir="ltr">{v === null ? '—' : formatNumber(v, lang, 1)}</bdi></td></tr>
              ))}
            </Table>
            </div>
          ) : (
            <dl className="det-kpi-kv" aria-label={t('k24_name')}>
              {Object.entries(k24.breakdown).map(([k, v]) => (
                <div key={k} style={{ display: 'contents' }}>
                  <dt>{t(`k24_bd_${k}`)}<span className="det-bar" aria-hidden="true" style={{ maxWidth: 'none', marginTop: 4 }}><span style={{ inlineSize: `${Math.min(100, (v ?? 0) * 2)}%` }} /></span></dt>
                  <dd><bdi dir="ltr">{v === null ? '—' : formatNumber(v, lang, 1)}</bdi></dd>
                </div>
              ))}
            </dl>
          )}
          <div className="det-kpi-foot">
            <button type="button" className="det-linkbtn" onClick={() => setAsTable((v) => !v)}>{asTable ? t('show_chart') : t('show_table')}</button>
          </div>
        </section>
      </div>
      <form className="toolbar det-toolbar" onSubmit={(e) => e.preventDefault()}>
        <Field label={t('filter_period')} id="cf-period">
          <input id="cf-period" dir="ltr" placeholder="2026-Q3" value={filters.period} onChange={(e) => setFilters({ ...filters, period: e.target.value })} />
        </Field>
        <Field label={t('filter_tax')} id="cf-tax">
          <select id="cf-tax" value={filters.tax_type} onChange={(e) => setFilters({ ...filters, tax_type: e.target.value })}>
            <option value="">{t('all')}</option>
            <option value="vat">{t('vat')}</option>
            <option value="ct">{t('ct')}</option>
          </select>
        </Field>
        <Field label={t('filter_role')} id="cf-role">
          <select id="cf-role" value={filters.approver_role} onChange={(e) => setFilters({ ...filters, approver_role: e.target.value })}>
            <option value="">{t('all')}</option>
            {['owner', 'owner_abroad', 'authorised_signatory', 'delegate'].map((r) => (
              <option key={r} value={r}>{t(`role_${r}`)}</option>
            ))}
          </select>
        </Field>
        <div className="toolbar-end"><Button type="button" variant="secondary" onClick={() => setFilters({ period: '', tax_type: '', approver_role: '' })}>{t('clear_filters')}</Button></div>
      </form>
      <div className="det-two">
      <Panel title={t('exceptions_title')} id="exceptions" className={data.exceptions.length ? 'det-panel-flush' : undefined}>
        {data.exceptions.length === 0 ? (
          <p className="det-note"><Icon name="check" size={16} />{t('no_exceptions')}</p>
        ) : (
          <div className="table-compact det-table">
          <Table headers={[t('col_ref'), t('col_reason'), t('col_severity'), t('col_owner'), t('col_status')]}>
            {data.exceptions.map((x) => (
              <tr key={x.exception_id}>
                <td className="nowrap"><bdi dir="ltr">{x.submission_ref}</bdi></td>
                <td>{x.reason_label[lang]}</td>
                <td>{x.severity === 1 ? <Chip tone="critical">1</Chip> : <Chip tone="attention">2</Chip>}</td>
                <td>{t(`translation:roles.${x.case_owner_role}`)}</td>
                <td>{t(`rs_${x.review_status}`)}</td>
              </tr>
            ))}
          </Table>
          </div>
        )}
      </Panel>
      <Panel title={t('submissions_title')} id="submissions" actions={<span className="hint">{t('blocked_attempts', { n: data.blocked_attempts.length })}</span>}>
        <p className="det-note"><Icon name="info" size={16} /><span><strong>{t('readback_title')}</strong> {t('readback_na')}</span></p>
        {data.submissions.length === 0 ? (
          <Empty title={t('comp_empty')} body={t('comp_empty2')} action={<Button variant="secondary" onClick={() => setFilters({ period: '', tax_type: '', approver_role: '' })}>{t('clear_filters')}</Button>} />
        ) : (
          <div className="table-compact det-table">
          <Table headers={[t('col_ref'), t('col_tax'), t('col_time'), t('col_match'), t('col_readback')]}>
            {data.submissions.map((s) => (
              <tr key={s.submission_ref}>
                <td className="nowrap"><bdi dir="ltr">{s.submission_ref}</bdi>{s.self_reported && <span className="det-cell-sub">{t('self_reported_tag')}</span>}</td>
                <td className="nowrap">{s.tax_type ? t(s.tax_type) : '—'}</td>
                <td className="date-cell" title={formatDateTime(s.at, lang)}>{formatDubaiDate(s.at, lang)}</td>
                <td>{s.match_status === 'valid' ? <Chip tone="ok">{t('match_valid')}</Chip> : <Chip tone="urgent">{t('match_exception')}</Chip>}</td>
                <td className="nowrap">{t('not_available')}</td>
              </tr>
            ))}
          </Table>
          </div>
        )}
      </Panel>
      </div>
    </div>
  )
}
