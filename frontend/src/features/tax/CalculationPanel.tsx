import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Icon } from '../../components/Icon'
import { Button, Chip, Disclosure, Field, Message, Skeleton, StatCard, Toolbar } from '../../components/ui'
import { get, post } from '../../lib/api'
import { formatAED, formatDate, formatDateTime } from '../../lib/format'
import { ctPeriods, errorKey, lastClosedQuarter, vatPeriods, type CalcView, type Calculation, type ChecklistItem, type Pack } from './types'

type Out = Record<string, unknown>
const num = (o: Out | null | undefined, k: string) => (o && typeof o[k] === 'number' ? (o[k] as number) : null)

function Figure({ label, fils, mark, lang, keyFigure }: { label: string; fils: number | null; mark?: string; lang: string; keyFigure?: boolean }) {
  return (
    <StatCard
      className={keyFigure ? 'tax-key' : undefined}
      label={label}
      value={<bdi dir="ltr">{fils === null ? '—' : formatAED(fils, lang)}</bdi>}
      status={mark ? <Chip tone="neutral">{mark}</Chip> : undefined}
    />
  )
}

/** SC6 calculation panel (E5-S2): one result card position for every state; never a partial figure on stop/error. */
export default function CalculationPanel({ companyId, taxType }: { companyId: string; taxType: 'vat' | 'ct' }) {
  const { t, i18n } = useTranslation('tax')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const nav = useNavigate()
  const periods = taxType === 'vat' ? vatPeriods() : ctPeriods()
  const [period, setPeriod] = useState(taxType === 'vat' ? lastClosedQuarter() : periods[1])
  const [view, setView] = useState<CalcView | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<{ text: string; ref?: string } | null>(null)
  const [checklist, setChecklist] = useState<ChecklistItem[] | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const msgRef = useRef<HTMLDivElement>(null)
  const url = `/api/companies/${companyId}/tax/${taxType}/${period}`
  const taxName = t(taxType === 'vat' ? 'tax_type_vat' : 'tax_type_ct')

  const load = useCallback(async () => {
    setError(null)
    setView(null)
    try {
      setView(await get<CalcView>(url))
    } catch (e) {
      const k = errorKey(e)
      setError({ text: t(k.key, k.values), ref: k.ref })
    }
    get<{ items: ChecklistItem[] }>(`/api/companies/${companyId}/drafts/checklist/${taxType}/${period}`).then((c) => setChecklist(c.items)).catch(() => setChecklist(null))
  }, [url, companyId, taxType, period, t])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (error) msgRef.current?.focus() }, [error])

  const run = async () => {
    setRunning(true)
    setError(null)
    try {
      await post(url)
      await load()
    } catch (e) {
      const k = errorKey(e)
      setError({ text: k.key === 'generic_error' ? t('run_failed', { ref: k.ref ?? '' }) : t(k.key, k.values), ref: k.ref })
    } finally {
      setRunning(false)
    }
  }

  const markReviewed = async () => {
    try {
      await post(`${url}/mark-reviewed`)
      await load()
    } catch (e) {
      setError({ text: t(errorKey(e).key) })
    }
  }

  const escalate = async () => {
    try {
      const out = await post<{ expected_response_hours: number }>(`${url}/escalate`, { note: 'owner asked a human specialist' })
      setNotice(t('escalate_sent', { hours: out.expected_response_hours }))
    } catch (e) {
      setError({ text: t(errorKey(e).key) })
    }
  }

  const createDraft = async () => {
    try {
      const pack = await post<Pack>(`/api/companies/${companyId}/drafts`, { tax_type: taxType, period_id: period })
      nav(`/returns/${pack.id}`)
    } catch (e) {
      const k = errorKey(e)
      setError({ text: t(k.key, k.values) })
    }
  }

  const c: Calculation | null | undefined = view?.calculation
  const o = (c?.outputs ?? null) as Out | null
  const canPrepare = !!view?.can_prepare
  const ruleRef = c?.rule_refs ? c.rule_refs[taxType === 'vat' ? 'vat-rate' : 'ct-rate'] : null

  const selector = (
    <Toolbar label={t('period')}>
      <Field label={t('period')} id={`period-${taxType}`} hint={t('gloss_period')}>
        <select id={`period-${taxType}`} value={period} onChange={(e) => setPeriod(e.target.value)}>
          {periods.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </Field>
      {c?.due_date && (
        <div className="tax-due">
          <Icon name="calendar" size={18} />
          <span>{t('due', { date: formatDate(c.due_date, lang), source: t(`due_source_${c.due_date_source}`) })}</span>
        </div>
      )}
      {canPrepare && c && !['no_rule_stop', 'blocked', 'missing_vat_code', 'run_failed'].includes(c.state) && view?.role !== 'remote_owner' && (
        <div className="toolbar-end">
          <Button variant="secondary" onClick={run}>{t('recalculate')}</Button>
          <Button variant="secondary" onClick={markReviewed} disabled={c.state !== 'current' || c.review_status === 'reviewed'}>{t('mark_reviewed')}</Button>
          <Button onClick={createDraft} disabled={c.state === 'stale'}>{t('create_draft')}</Button>
        </div>
      )}
    </Toolbar>
  )

  const body = () => {
    if (running) return <div aria-busy="true"><p role="status">{t('calculating', { period })}</p><Skeleton rows={4} /></div>
    if (!view) return error ? null : <Skeleton rows={4} />
    if (!c) {
      return (
        <Message kind="info">
          {view.empty === 'add_trn' ? t('add_trn') : t('confirm_to_calculate', { period })}
          {canPrepare && view.empty !== 'add_trn' && <div className="actions"><Button onClick={run}>{t('calculate')}</Button></div>}
        </Message>
      )
    }
    if (view.role === 'remote_owner') {
      return (
        <div>
          <Chip tone={c.state === 'current' ? 'ok' : 'attention'}>{t(`state_${c.state}`)}</Chip>
          {c.net_figure_fils != null && <div className="stat-grid tax-figs"><Figure label={taxType === 'vat' ? t('net_vat') : t('tax')} fils={c.net_figure_fils} lang={lang} keyFigure /></div>}
          <p className="hint">{t('summary_view')}</p>
        </div>
      )
    }
    if (c.state === 'no_rule_stop') {
      return (
        <div className="panel-body" role="status">
          <p><span aria-hidden="true">⛔ </span>{t('no_rule_stop', { taxType: taxName, period })}</p>
          {c.notification_ref && <p className="hint">{t('notified', { ref: c.notification_ref, datetime: formatDateTime(c.notification_sent_at, lang) })}</p>}
          {c.what_we_have && (
            <details>
              <summary>{t('what_we_have')}</summary>
              <p>{t('what_we_have_counts', { confirmed: c.what_we_have.confirmed_transactions, needs: c.what_we_have.needs_review })}</p>
            </details>
          )}
        </div>
      )
    }
    if (c.state === 'blocked') {
      return (
        <Message kind="warning">
          <p>{t('scope_block')}</p>
          <Chip tone="info" icon="↗">{t('escalated')}</Chip>
        </Message>
      )
    }
    if (c.state === 'missing_vat_code') return <Message kind="error">{t('missing_vat_code', { n: c.excluded_count })}</Message>
    if (c.state === 'run_failed') return <Message kind="error">{t('run_failed', { ref: c.id })}</Message>
    const stale = c.state === 'stale'
    const sbr = (o?.sbr ?? null) as Out | null
    return (
      <div>
        {stale && (
          <Message kind="warning">
            <Chip tone="attention" icon="⟳">{t('stale_badge')}</Chip> {t('stale', { datetime: formatDateTime(c.created_at, lang) })}
            {canPrepare && <div className="actions"><Button onClick={run}>{t('recalculate')}</Button></div>}
          </Message>
        )}
        {c.state === 'incomplete' && (
          <Message kind="warning">
            {t('excludes_warning', { n: c.excluded_count, x: formatAED(c.excluded_total_fils, lang) })}
            <div><Chip tone="attention" icon="!">{t('incomplete')}</Chip> <Chip tone="neutral">{t('excludes_n', { n: c.excluded_count })}</Chip></div>
          </Message>
        )}
        <div className="tax-labels">
          <Chip tone="draft" icon="✎">{c.review_status === 'reviewed' && c.reviewed_by ? t('reviewed_by', { name: c.reviewed_by.name, role: c.reviewed_by.role, date: formatDate(c.reviewed_by.at, lang) }) : t('ai_not_reviewed')}</Chip>
          {ruleRef && <Chip tone="info" icon="§">{t('rules_used', { version: ruleRef.version, date: formatDate(ruleRef.effective_from, lang) })}</Chip>}
          <span className="hint">{t('version_n', { n: c.version })}</span>
        </div>
        <h3 className="visually-hidden">{t('key_figures')}</h3>
        <div className="stat-grid tax-figs" style={{ opacity: stale ? 0.5 : 1 }} aria-disabled={stale}>
          {taxType === 'vat' ? (
            <>
              <Figure label={t('out_vat')} fils={num(o, 'output_vat_fils')} mark={t('line_calculated')} lang={lang} />
              <Figure label={t('in_vat')} fils={num(o, 'input_vat_fils')} mark={t('line_calculated')} lang={lang} />
              <Figure label={t('net_vat')} fils={num(o, 'net_vat_fils')} mark={t('line_calculated')} lang={lang} keyFigure />
            </>
          ) : (
            <>
              <Figure label={t('acc_profit')} fils={num(o, 'accounting_profit_fils')} mark={o?.accounting_profit_source === 'classified' ? t('line_calculated') : t('line_person_entered')} lang={lang} />
              <Figure label={t('adjustments')} fils={num(o, 'adjustments_total_fils')} lang={lang} />
              <Figure label={t('taxable_income')} fils={num(o, 'taxable_income_fils')} mark={t('line_calculated')} lang={lang} />
              <Figure label={t('band_0')} fils={num(o, 'band_0_fils')} lang={lang} />
              <Figure label={t('band_9')} fils={num(o, 'band_9_fils')} lang={lang} />
              <Figure label={t('tax')} fils={num(o, 'tax_fils')} mark={t('line_calculated')} lang={lang} keyFigure />
            </>
          )}
        </div>
        <p className="hint">{t('estimates')} {t('configured_pending')}.</p>
        {taxType === 'ct' && sbr && (
          <section className="card tax-sbr" aria-labelledby={`sbr-${taxType}`}>
            <div className="tax-sbr-head">
              <h3 id={`sbr-${taxType}`}>{String(sbr.indicator) === 'may be eligible' ? t('sbr_may_be') : t('sbr_not_eligible')}</h3>
              <Chip tone={sbr.indicator === 'may be eligible' ? 'info' : 'neutral'}>{sbr.indicator === 'may be eligible' ? t('sbr_eligible') : t('sbr_not_eligible')}</Chip>
            </div>
            {typeof sbr.reason === 'string' && <p>{t('sbr_reason', { reason: sbr.reason })}</p>}
            <p>{t('sbr_revenue', { amount: formatAED(num(sbr, 'revenue_fils'), lang), source: String(sbr.revenue_source ?? '') })}</p>
            <p>{t('sbr_election', { status: String(sbr.election_status) })}</p>
            <p className="hint">{t('sbr_indicator_only')}</p>
            <Disclosure summary={t('calculation_basis')}>
              <p>{t('sbr_instrument', { instrument: String(sbr.instrument), review: String(sbr.review_status) })}</p>
              {typeof sbr.cutoff_date === 'string' && <p>{t('sbr_applied_until', { date: formatDate(sbr.cutoff_date, lang) })}</p>}
            </Disclosure>
          </section>
        )}
        {taxType === 'ct' && Array.isArray(o?.flagged_items) && (o?.flagged_items as Out[]).length > 0 && (
          <Message kind="info">
            {t('flagged_items')}: {(o?.flagged_items as Out[]).map((f) => String(f.label)).join(', ')} <Chip tone="info">{t('escalated')}</Chip>
          </Message>
        )}
        {(c.excluded_items?.length ?? 0) > 0 && (
          <Disclosure summary={<>{t('excluded_list')}: {t('excluded_header', { n: c.excluded_count, total: formatAED(c.excluded_total_fils, lang) })}</>}>
            <div className="table-wrap">
              <table className="table-compact">
                <thead><tr><th scope="col">{t('col_date')}</th><th scope="col">{t('col_description')}</th><th scope="col" className="num">{t('col_amount')}</th><th scope="col">{t('col_reason')}</th><th scope="col">{t('col_actions')}</th></tr></thead>
                <tbody>
                  {c.excluded_items!.map((e, i) => (
                    <tr key={i}>
                      <td className="date-cell"><bdi dir="ltr">{formatDate(e.date, lang)}</bdi></td>
                      <td><bdi dir="auto">{e.description}</bdi></td>
                      <td className="num"><bdi dir="ltr">{formatAED(e.aed_amount_fils, lang)}</bdi></td>
                      <td>{e.reason}</td>
                      <td><Link to="/tax?tab=books">{t('review_item')}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Disclosure>
        )}
        <Disclosure summary={t('trace')}>
          <ol className="tax-trace">
            {(c.trace ?? []).map((s, i) => (
              <li key={i}><span>{String(s.step)}</span> <code dir="ltr" className="hint">{JSON.stringify(Object.fromEntries(Object.entries(s).filter(([k]) => k !== 'step')))}</code></li>
            ))}
          </ol>
          {taxType === 'vat' && Array.isArray(o?.lines) && (
            <>
              <h4>{t('source_data')}</h4>
              <ul>
                {(o?.lines as Out[]).map((ln) => (
                  <li key={String(ln.classification_id)}>
                    <bdi dir="auto">{String(ln.description)}</bdi> · <bdi dir="ltr">{String(ln.vat_code)} {String(ln.tax_point_date)}</bdi> · {String(ln.tax_point_rule)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Disclosure>
        {c.comparison?.available && (
          <p className="hint">
            {c.comparison.same ? t('same_result') : (
              <>
                {t('current_rules', { version: c.comparison.current?.version ?? '' })} · {t('difference')}: {t(c.comparison.word === 'higher by' ? 'higher_by' : 'lower_by')} <bdi dir="ltr">{formatAED(Math.abs(c.comparison.difference_fils ?? 0), lang)}</bdi>. {t('comparison_info')}
              </>
            )}
          </p>
        )}
        {!c.can_approve && c.approval_disabled_reason && <p className="hint">{c.state === 'incomplete' ? t('approval_off') : stale ? t('approval_current_only') : c.approval_disabled_reason}</p>}
      </div>
    )
  }

  return (
    <div>
      {selector}
      {view?.view_only_reason && view.role !== 'remote_owner' && (
        <Message kind="info">{t('view_only')} <Button variant="link">{t('ask_owner_access')}</Button></Message>
      )}
      <div ref={msgRef} tabIndex={-1}>
        {error && <Message kind="error">{error.text}{error.ref ? ` (${error.ref})` : ''}</Message>}
        {notice && <Message kind="success">{notice}</Message>}
      </div>
      {body()}
      {checklist && checklist.length > 0 && (
        <section className="card tax-checklist" aria-labelledby={`checklist-${taxType}`}>
          <div className="tax-sbr-head">
            <h3 id={`checklist-${taxType}`}>{t('checklist_title')}</h3>
          </div>
          <p className="hint">{t('missing_items', { n: checklist.length })}</p>
          <ul className="tax-check-list">
            {checklist.map((m) => (
              <li key={m.key}>
                <span className="tax-check-icon" aria-hidden="true"><Icon name="alert" size={18} /></span>
                <div className="tax-check-main">
                  <div className="tax-check-title">{t(`item_${m.key}`)} <Chip tone="attention">{t('missing')}</Chip></div>
                  <div className="hint">{t('col_why')}: {m.why} · {t('col_who')}: {t(`who_${m.who}`)}</div>
                </div>
                <div className="tax-check-action">{m.owner_only ? <>{t('only_owner_can')} <Button variant="link">{t('notify_owner')}</Button></> : m.action}</div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="hint">
        {t('not_advice')} <Button variant="link" onClick={escalate}>{t('escalate')}</Button> · <Link to="/help">{t('ask_a_human')}</Link>
      </p>
    </div>
  )
}
