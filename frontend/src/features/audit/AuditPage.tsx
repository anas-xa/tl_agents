import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Disclosure, Empty, Field, Ident, Message, PageHeader, Panel, Skeleton, StatCard } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatAED, formatDate, formatDateTime } from '../../lib/format'
import type { AuditOverview, Bi, FlagDetail, FlagRow, Indicator, WorkingFile } from './types'
import './audit.css'

const pick = (b: Bi | null | undefined, lang: string) => (b ? (lang === 'ar' ? b.ar : b.en) : '')
const SEV_TONE = { High: 'urgent', Medium: 'attention', Low: 'neutral' } as const
const STATUS_TONE = { New: 'info', Confirmed: 'ok', Explained: 'neutral', Dismissed: 'neutral', Escalated: 'attention' } as const
const STATE_TONE = { likely_required: 'attention', likely_not_required: 'neutral', cannot_determine: 'info', not_yet_assessed: 'neutral' } as const

/** SC8 Audit preparation status: indicator card, items for review, audit work draft. */
export default function AuditPage() {
  const { t, i18n } = useTranslation('audit')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { companyId, company } = useAuth()
  const [data, setData] = useState<AuditOverview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => {
    if (!companyId) return
    get<AuditOverview>(`/api/companies/${companyId}/audit`).then((d) => { setData(d); setErr(null) }).catch((e: ApiError) => setErr(e.code))
  }, [companyId])
  useEffect(() => { load() }, [load])
  const companyName = company ? (lang === 'ar' ? company.trade_name_ar : company.trade_name_en) : null
  const header = (
    <PageHeader
      eyebrow={companyName ? <bdi>{companyName}</bdi> : undefined}
      title={t('title')}
      subtitle={t('ui.subtitle')}
      meta={data?.flag.is_demo ? <Chip tone="neutral">{t('demo')}</Chip> : undefined}
    />
  )
  if (err && !data) return <div className="page aud-page">{header}<Message kind="error">{t('error')} <Button variant="link" onClick={load}>{t('indicator.try_again')}</Button></Message></div>
  if (!data) return <div className="page aud-page">{header}<p aria-busy="true">{t('indicator.loading')}</p><Skeleton rows={6} /></div>
  return (
    <div className="page aud-page">
      {header}
      <Summary data={data} lang={lang} />
      <IndicatorCard data={data} lang={lang} companyId={companyId!} onChange={load} />
      <ExceptionsSection data={data} lang={lang} companyId={companyId!} onChange={load} />
      <WorkingFileSection data={data} lang={lang} companyId={companyId!} onChange={load} />
    </div>
  )
}

/** Summary row: the likely requirement (with its indicative label), open review items and the work-draft status. */
function Summary({ data, lang }: { data: AuditOverview; lang: string }) {
  const { t } = useTranslation('audit')
  const f = data.flag
  const text = f.text[lang as 'en' | 'ar'] || {}
  const rows = data.exceptions ?? []
  const fresh = rows.filter((r) => r.status === 'New' || r.status === 'Escalated').length
  const wf = data.working_file
  const stateIcon = { likely_required: 'alert', likely_not_required: 'check', cannot_determine: 'help', not_yet_assessed: 'clock' } as const
  const stateTone = { likely_required: 'attention', likely_not_required: 'ok', cannot_determine: 'info', not_yet_assessed: 'info' } as const
  return (
    <div className="stat-grid aud-summary">
      <StatCard
        icon={stateIcon[f.state]}
        tone={stateTone[f.state]}
        label={t('ui.indicator_label')}
        value={t(`indicator.states.${f.state}`)}
        status={text.badge_indicative ? <Chip tone="info" icon="ⓘ">{text.badge_indicative}</Chip> : undefined}
        footer={<a href="#audit-indicator">{t('ui.more')}</a>}
      />
      {data.exceptions !== null && (
        <StatCard
          icon="search"
          tone={fresh > 0 ? 'attention' : 'ok'}
          label={t('ui.items_label')}
          value={rows.length ? t('ui.items_value', { n: fresh }) : t('ui.items_none')}
          hint={rows.length ? t('ui.items_hint', { m: rows.length }) : undefined}
          footer={<a href="#audit-exceptions">{t('exceptions.title')}</a>}
        />
      )}
      {!data.working_file_hidden && (
        <StatCard
          icon="file"
          tone={wf ? (wf.completeness_state === 'incomplete' ? 'attention' : 'info') : undefined}
          label={t('ui.file_label')}
          value={wf ? pick(wf.status_label, lang) : t('ui.no_file')}
          hint={wf ? t('file.gaps_summary', { n: wf.gaps_summary.complete, m: wf.gaps_summary.total }) : undefined}
          status={wf ? <Chip tone={wf.completeness_state === 'incomplete' ? 'attention' : 'info'}>{t(`file.completeness.${wf.completeness_state}`)}</Chip> : undefined}
          footer={<a href="#audit-file">{t('file.title')}</a>}
        />
      )}
    </div>
  )
}

function IndicatorCard({ data, lang, companyId, onChange }: { data: AuditOverview; lang: string; companyId: string; onChange: () => void }) {
  const { t } = useTranslation('audit')
  const f: Indicator = data.flag
  const text = f.text[lang as 'en' | 'ar'] || {}
  const [msg, setMsg] = useState<{ kind: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [disputeOpen, setDisputeOpen] = useState(false)
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const headingRef = useRef<HTMLHeadingElement>(null)
  const act = async (action: string, body: Record<string, unknown> = {}) => {
    try {
      const r = await post<{ case_id?: string; case_reference?: string; target_working_days?: number }>(`/api/companies/${companyId}/audit/flag/actions`, { action, ...body })
      if (action === 'request_review') setMsg({ kind: 'success', text: t('indicator.review_opened', { ref: r.case_reference ?? r.case_id, n: r.target_working_days }) })
      if (action === 'dispute') { setMsg({ kind: 'success', text: t('indicator.disputed') }); setDisputeOpen(false) }
      onChange()
      headingRef.current?.focus()
    } catch (e) {
      const code = (e as ApiError).code
      setMsg({ kind: 'error', text: code === 'FEATURE_SWITCHED_OFF' ? t('indicator.ask_auditor_off') : code === 'READ_ONLY_ROLE' ? t('indicator.read_only') : code === 'OWNER_CANNOT_OVERRIDE' ? t('indicator.cannot_override') : (e as Error).message })
    }
  }
  const headline = text.headline_likely_required || text.headline_likely_not_required || text.cannot_determine_items || text.headline_cannot_determine || t('indicator.not_assessed')
  const readOnly = data.role === 'remote_owner' || (data.role === 'delegate' && !data.can.acknowledge)
  return (
    <Panel title={t('indicator.title')} id="audit-indicator" className="aud-indicator">
      <div className="aud-headline">
        <h3 ref={headingRef} tabIndex={-1}>
          <Chip tone={STATE_TONE[f.state]}>{t(`indicator.states.${f.state}`)}</Chip> <span>{headline}</span>
        </h3>
      </div>
      {f.not_refreshed && <Message kind="warning">{t('indicator.not_refreshed', { date: formatDateTime(f.evaluated_at, lang) })} <Button variant="link" onClick={() => post(`/api/companies/${companyId}/audit/flag/recompute`).then(onChange)}>{t('indicator.try_again')}</Button></Message>}
      {f.case && <div className="aud-note" role="status"><p>{f.near_threshold ? t('indicator.case_strip') : t('indicator.person')}</p><p className="muted">{f.case.status} · {formatDate(f.case.opened_at, lang)} · <Link to="/help">{t('indicator.case_open')}</Link></p></div>}
      {f.change_notice && !f.banner_hidden && (
        <div role="status" className="aud-note">
          <p>{t('indicator.change_notice', { old: t(`indicator.states.${f.previous_result}`), new: t(`indicator.states.${f.state}`) })}</p>
          {!readOnly && <Button variant="secondary" className="btn-sm" onClick={() => act('acknowledge')}>{t('indicator.got_it')}</Button>}
        </div>
      )}
      {['may_be_required', 'not_indicated_detail', 'shown_because_revenue', 'near_threshold_strip', 'at_threshold', 'caveat_revenue_only'].filter((k) => text[k]).map((k) => <p key={k}>{text[k]}</p>)}
      {f.state === 'cannot_determine' && (f.checklist?.length ?? 0) > 0 && (
        <div>
          <p>{t('indicator.checklist')}</p>
          <ul className="aud-checklist">{f.checklist!.map((c) => <li key={c.item}><span className="aud-check-icon aud-check-open" aria-hidden="true"><Icon name="alert" size={16} /></span><span><Chip tone="attention">{t('indicator.missing')}</Chip> {lang === 'ar' ? c.ar : c.en}{c.gloss_en && <span className="muted"> — {lang === 'ar' ? c.gloss_ar : c.gloss_en}</span>}</span></li>)}</ul>
        </div>
      )}
      {text.next_steps && <p>{text.next_steps} {text.free_choice}</p>}
      <p className="helper">{text.disclaimer}</p>
      <Disclosure summary={t('indicator.why')}>
        {(f.cannot_determine_reasons?.length ?? 0) > 0 && <ul>{f.cannot_determine_reasons!.map((r) => <li key={r}>{t(`indicator.reasons.${r}`)}</li>)}</ul>}
        {f.period_start && <p>{t('indicator.period', { start: formatDate(f.period_start, lang), end: formatDate(f.period_end, lang) })}</p>}
        {f.revenue_source && <p>{t('indicator.source', { source: t(`indicator.sources.${f.revenue_source}`) })}</p>}
        {f.twelve_month_equivalent_fils != null && <p>{t('indicator.equivalent', { amount: formatAED(f.twelve_month_equivalent_fils, lang) })}</p>}
        {f.criteria_version && <p className="muted">{t('indicator.criteria', { v: f.criteria_version, instrument: f.instrument })}</p>}
        <p className="helper">{text.disclaimer_basis}</p>
      </Disclosure>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      {readOnly ? <p className="muted">{pick(data.read_only_note, lang) || t('indicator.read_only')}</p> : f.state !== 'not_yet_assessed' && (
        <div className="actions aud-actions">
          {f.change_notice && !f.banner_hidden && data.can.hide_banner && <Button variant="secondary" onClick={() => act('hide_banner')}>{t('indicator.hide')}</Button>}
          {data.can.dispute && <Button variant="secondary" onClick={() => setDisputeOpen(!disputeOpen)} aria-expanded={disputeOpen}>{t('indicator.dispute')}</Button>}
          {data.can.request_review && <Button variant="secondary" onClick={() => act('request_review')}>{t('indicator.request_review')}</Button>}
          <Button variant="link" aria-disabled="true" title={t('indicator.ask_auditor_off')} onClick={() => setMsg({ kind: 'info', text: t('indicator.ask_auditor_off') })}>{t('indicator.ask_auditor')}</Button>
        </div>
      )}
      {disputeOpen && (
        <form className="aud-dispute" onSubmit={(e) => { e.preventDefault(); act('dispute', { reason_code: code, reason: note || undefined }) }}>
          <Field label={t('indicator.dispute_reason')} id="dispute-code" required>
            <select id="dispute-code" value={code} onChange={(e) => setCode(e.target.value)} required>
              <option value="" />
              {['revenue_wrong', 'tax_group_wrong', 'qfzp_wrong', 'period_wrong', 'other'].map((c) => <option key={c} value={c}>{t(`indicator.dispute_codes.${c}`)}</option>)}
            </select>
          </Field>
          <Field label={t('indicator.dispute_note')} id="dispute-note"><textarea id="dispute-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} /></Field>
          <Button type="submit" disabled={!code}>{t('indicator.dispute')}</Button>
        </form>
      )}
    </Panel>
  )
}

function ExceptionsSection({ data, lang, companyId, onChange }: { data: AuditOverview; lang: string; companyId: string; onChange: () => void }) {
  const { t } = useTranslation('audit')
  const [sev, setSev] = useState('')
  const [status, setStatus] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  if (data.exceptions === null) return <Panel title={t('exceptions.title')} id="audit-exceptions"><Empty icon="lock" title={pick(data.exceptions_hidden_reason, lang)} /></Panel>
  const rows = data.exceptions.filter((r) => (!sev || r.severity === sev) && (!status || r.status === status))
  const rv = data.review
  const run = () => { setRunning(true); post(`/api/companies/${companyId}/audit/review/run`).finally(() => { setRunning(false); onChange() }) }
  if (sel) return <FlagDetailPanel id={sel} data={data} lang={lang} companyId={companyId} onBack={() => { setSel(null); onChange() }} />
  const statusIcon = (st: FlagRow['status']) => (st === 'New' ? 'clock' : st === 'Escalated' ? 'alert' : 'check')
  return (
    <Panel title={t('exceptions.title')} id="audit-exceptions" className="aud-exceptions" actions={data.can.run_review && <Button variant="secondary" className="btn-sm" onClick={run} disabled={running}>{t('exceptions.run')}</Button>}>
      {data.exceptions.length === 0 && <p className="helper">{t('flag_prompt')}</p>}
      {running && <p role="status">{t('exceptions.in_progress', { date: formatDateTime(rv?.last_cycle_at, lang) })}</p>}
      {rv?.more_available && <Message kind="info">{t('exceptions.more_available')}</Message>}
      {rv?.empty_state === 'consent_withdrawn' && <Message kind="warning">{t('exceptions.empty_c', { date: formatDate(rv.ended_on, lang) })} <Link to="/consent">{t('exceptions.open_consent')}</Link></Message>}
      {data.exceptions.length === 0 ? (
        rv?.empty_state === 'no_source' ? <Empty icon="link" title={t('exceptions.empty_b')} action={<><Link className="btn btn-primary" to="/consent">{t('exceptions.connect')}</Link> <span className="muted">{t('exceptions.manual')}</span></>} />
          : rv?.empty_state === 'no_review_yet' ? <Empty icon="search" title={t('exceptions.no_review_yet')} action={data.can.run_review ? <Button variant="secondary" onClick={run} disabled={running}>{t('exceptions.run')}</Button> : undefined} /> : rv?.empty_state === 'consent_withdrawn' ? null : <Empty icon="check" title={t('exceptions.empty_a')} body={rv?.last_cycle_at ? formatDateTime(rv.last_cycle_at, lang) : undefined} />
      ) : (
        <>
          <div className="aud-filter-row">
          <p className="helper">{t('flag_prompt')}</p>
          <div className="aud-filters" role="group" aria-label={t('ui.filters')}>
            <Field label={t('exceptions.cols.severity')} id="aud-sev">
              <select id="aud-sev" value={sev} onChange={(e) => setSev(e.target.value)}><option value="">{t('exceptions.severity.all')}</option>{['High', 'Medium', 'Low'].map((s) => <option key={s} value={s}>{t(`exceptions.severity.${s}`)}</option>)}</select>
            </Field>
            <Field label={t('exceptions.cols.status')} id="aud-status">
              <select id="aud-status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t('exceptions.status.all')}</option>{['New', 'Confirmed', 'Explained', 'Dismissed', 'Escalated'].map((s) => <option key={s} value={s}>{t(`exceptions.status.${s}`)}</option>)}</select>
            </Field>
          </div>
          </div>
          {rows.length === 0 ? <Empty icon="search" title={t('exceptions.empty_d')} action={<Button variant="secondary" onClick={() => { setSev(''); setStatus('') }}>{t('exceptions.clear_filters')}</Button>} /> : (
            <ul className="aud-items">
              {rows.map((r: FlagRow) => (
                <li key={r.id} className={`aud-item aud-item-${r.status === 'New' || r.status === 'Escalated' ? 'open' : 'done'}`}>
                  <span className={`aud-check-icon ${r.status === 'New' || r.status === 'Escalated' ? 'aud-check-open' : 'aud-check-done'}`} aria-hidden="true"><Icon name={statusIcon(r.status)} size={16} /></span>
                  <div className="aud-item-main">
                    <button type="button" className="aud-item-title" onClick={() => setSel(r.id)}>{pick(r.rule_title, lang)}</button>
                    <div className="aud-item-meta">
                      <Chip tone={STATUS_TONE[r.status]}>{t(`exceptions.status.${r.status}`)}</Chip>
                      <Chip tone={SEV_TONE[r.severity]}>{t(`exceptions.severity.${r.severity}`)}</Chip>
                      <span>{t(`exceptions.source.${r.source}`, { defaultValue: r.source })}</span>
                      <span className="nowrap">{t('exceptions.cols.flagged')} {formatDate(r.flagged_at, lang)}</span>
                      {r.source_withdrawn && <Chip tone="neutral" icon="🔒">{t('exceptions.hidden_row')}</Chip>}
                      {r.evidence_changed_since && <Chip tone="attention" icon="!">{t('exceptions.evidence_changed', { date: formatDate(r.evidence_changed_since, lang) })}</Chip>}
                      <Chip tone="draft" icon="✎">{pick(r.ai_label, lang)}</Chip>
                      {r.is_demo && <Chip tone="neutral">{t('demo')}</Chip>}
                    </div>
                  </div>
                  <div className="aud-item-amount num">{r.amount_fils != null ? <bdi dir="ltr">{formatAED(r.amount_fils, lang)}</bdi> : '—'}</div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {rv?.last_cycle_at && <p className="muted aud-foot">{t('exceptions.last_review', { date: formatDateTime(rv.last_cycle_at, lang), sources: rv.sources_read.map((s) => t(`exceptions.source.${s}`)).join(', ') || '—' })}</p>}
    </Panel>
  )
}

function FlagDetailPanel({ id, data, lang, companyId, onBack }: { id: string; data: AuditOverview; lang: string; companyId: string; onBack: () => void }) {
  const { t } = useTranslation('audit')
  const [d, setD] = useState<FlagDetail | null>(null)
  const [decision, setDecision] = useState('')
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const historyRef = useRef<HTMLHeadingElement>(null)
  const load = useCallback(() => get<FlagDetail>(`/api/companies/${companyId}/audit/exceptions/${id}`).then(setD).catch(() => setMsg({ kind: 'error', text: t('error') })), [companyId, id, t])
  useEffect(() => { load() }, [load])
  if (!d) return <Panel title={t('exceptions.title')}><Skeleton rows={4} /></Panel>
  const canDecide = data.can.decide
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const out = await post<FlagDetail>(`/api/companies/${companyId}/audit/exceptions/${id}/decide`, { decision, reason })
      setD(out)
      setMsg({ kind: 'success', text: t('exceptions.saved', { name: out.decisions[0]?.by, date: formatDateTime(out.decisions[0]?.at, lang) }) })
      setDecision(''); setReason('')
      historyRef.current?.focus()
    } catch (err) {
      setMsg({ kind: 'error', text: (err as ApiError).status ? (err as Error).message : t('exceptions.not_saved') })
    }
  }
  const escalate = () => post<FlagDetail>(`/api/companies/${companyId}/audit/exceptions/${id}/decide`, { decision: 'escalate' }).then(setD).catch((e: ApiError) => setMsg({ kind: 'error', text: e.message }))
  return (
    <Panel title={pick(d.rule_title, lang)} id="flag-detail" actions={<Button variant="secondary" onClick={onBack}>{t('exceptions.close')}</Button>}>
      <div className="aud-labels"><Chip tone={STATUS_TONE[d.status]}>{t(`exceptions.status.${d.status}`)}</Chip> <Chip tone={SEV_TONE[d.severity]}>{t(`exceptions.severity.${d.severity}`)}</Chip> <Chip tone="draft" icon="✎">{pick(d.ai_label, lang)}</Chip></div>
      <p className="helper">{t('flag_prompt')}</p>
      <Disclosure summary={t('ui.rule_details')}>
        <p>{t('exceptions.triggered_by', { name: d.rule_id, n: d.rule_version })}{d.rule_label && ` · ${t('exceptions.cash_label')}`}</p>
      </Disclosure>
      {d.source_withdrawn && <Message kind="info">{t('exceptions.source_withdrawn')}</Message>}
      {d.based_on_data_up_to && <p className="muted">{t('exceptions.based_on', { date: formatDate(d.based_on_data_up_to, lang) })}</p>}
      {d.evidence_changed_since && <Message kind="warning">{t('exceptions.evidence_changed', { date: formatDate(d.evidence_changed_since, lang) })}</Message>}
      <h3 className="aud-sub">{t('exceptions.evidence')}</h3>
      <div className="table-wrap">
        <table className="table-compact">
          <thead><tr><th scope="col">{t('exceptions.evidence_cols.record')}</th><th scope="col">{t('exceptions.evidence_cols.date')}</th><th scope="col" className="num aud-num">{t('exceptions.evidence_cols.amount')}</th><th scope="col">{t('exceptions.evidence_cols.counterparty')}</th><th scope="col">{t('exceptions.evidence_cols.reference')}</th></tr></thead>
          <tbody>
            {d.evidence.map((r) => r.masked ? (
              <tr key={r.record_id} aria-label={t('exceptions.hidden_row_name')}><td><Ident>{r.record_id}</Ident></td><td className="date-cell">{formatDate(r.date, lang)}</td><td colSpan={3}><span aria-hidden="true">🔒 </span>{t('exceptions.hidden_row')}</td></tr>
            ) : (
              <tr key={r.record_id}><td className="nowrap"><Ident>{r.record_id}</Ident></td><td className="date-cell">{formatDate(r.date, lang)}</td><td className="num aud-num"><bdi dir="ltr">{formatAED(r.amount_fils ?? null, lang)}</bdi></td><td><bdi>{r.counterparty ?? '—'}</bdi></td><td className="nowrap"><Ident>{r.invoice_number ?? r.account_code ?? '—'}</Ident></td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.revisions.length > 1 && (
        <Disclosure summary={t('exceptions.see_changes')}>
          <ol className="timeline">{d.revisions.map((r) => <li key={r.revision_no}><span>#{r.revision_no}</span><span className="nowrap">{formatDateTime(r.created_at, lang)}</span><span>{r.actor}</span><span>{r.change_summary}</span></li>)}</ol>
        </Disclosure>
      )}
      <h3 className="aud-sub">{t('exceptions.decision')}</h3>
      {!canDecide && <p id="no-right" className="helper">{pick(data.decide_disabled_reason, lang) || t('exceptions.no_right')}</p>}
      <form onSubmit={save} aria-describedby={!canDecide ? 'no-right' : undefined}>
        <fieldset className="aud-decide" aria-disabled={!canDecide}>
          <legend className="visually-hidden">{t('exceptions.decision')}</legend>
          {['confirm', 'explain', 'dismiss'].map((k) => (
            <label key={k} className="aud-radio"><input type="radio" name="decision" value={k} checked={decision === k} onChange={() => canDecide && setDecision(k)} aria-disabled={!canDecide} /> <span>{t(`exceptions.${k}`)}</span></label>
          ))}
        </fieldset>
        <Field label={t('exceptions.reason')} id="decision-reason" hint={t('exceptions.counter', { n: reason.trim().length })}>
          <textarea id="decision-reason" value={reason} onChange={(e) => setReason(e.target.value)} readOnly={!canDecide} aria-disabled={!canDecide} />
        </Field>
        <Button type="submit" aria-disabled={!canDecide || !decision || reason.trim().length < 10} disabled={!canDecide || !decision || reason.trim().length < 10}>{t('exceptions.save')}</Button>
        {data.can.escalate && canDecide && <> <Button type="button" variant="secondary" onClick={escalate}>{t('exceptions.escalate')}</Button></>}
      </form>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <h3 className="aud-sub" ref={historyRef} tabIndex={-1}>{t('exceptions.history')}</h3>
      <ol className="timeline">
        {d.decisions.map((x) => (
          <li key={x.id} style={x.superseded ? { textDecoration: 'line-through' } : undefined}>
            <span>{t(`exceptions.status.${x.decision === 'confirm' ? 'Confirmed' : x.decision === 'explain' ? 'Explained' : 'Dismissed'}`)}</span>
            <span>{x.by}{x.role_label ? ` (${x.role_label})` : ''}</span><span>{formatDateTime(x.at, lang)}</span>
            <span className="muted">{t('exceptions.applies_to', { n: x.revision_no })}</span>
            {x.quarantined && <Chip tone="attention">{t('exceptions.quarantined')}</Chip>}
            <span>{x.reason}</span>
          </li>
        ))}
      </ol>
    </Panel>
  )
}

function Stepper({ status, lang }: { status: WorkingFile['status'] | 'not_started'; lang: string }) {
  const { t } = useTranslation('audit')
  const steps = ['not_started', 'draft', 'under_review', 'signed', 'rejected'] as const
  return (
    <ol aria-label={t('file.stepper')} className="aud-stepper" lang={lang}>
      {steps.map((s, i) => {
        const current = s === status
        const unavailable = s === 'signed'
        const passed = steps.indexOf(status) > i && s !== 'rejected'
        return (
          <li key={s} className={`${current ? 'aud-step-current' : ''} ${passed ? 'aud-step-done' : ''}`} aria-current={current ? 'step' : undefined} aria-label={`${t('file.step_of', { n: i + 1, m: steps.length, name: t(`file.steps.${s}`) })}${current ? `, ${t('file.current')}` : ''}${unavailable ? `, ${t('file.signing_na')}` : ''}`}>
            <span className="aud-step-dot" aria-hidden="true">{passed ? <Icon name="check" size={14} /> : current ? '●' : ''}</span>
            <span className="aud-step-name">{t(`file.steps.${s}`)}{unavailable && <span className="muted aud-step-na"> ({t('file.signing_na')})</span>}</span>
          </li>
        )
      })}
    </ol>
  )
}

function WorkingFileSection({ data, lang, companyId, onChange }: { data: AuditOverview; lang: string; companyId: string; onChange: () => void }) {
  const { t } = useTranslation('audit')
  const [msg, setMsg] = useState<{ kind: 'info' | 'error' | 'warning'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  if (data.working_file_hidden) return <Panel title={t('file.title')} id="audit-file"><Empty icon="lock" title={pick(data.working_file_hidden, lang)} /></Panel>
  const f = data.working_file
  const prepare = () => {
    setBusy(true)
    setMsg({ kind: 'info', text: t('file.preparing') })
    post<{ refused: boolean; message?: Bi }>(`/api/companies/${companyId}/audit/working-file/prepare`).then((r) => { setMsg(r.refused ? { kind: 'warning', text: `${pick(r.message, lang)}` } : null); onChange() }).catch((e: ApiError) => setMsg({ kind: 'error', text: e.message })).finally(() => setBusy(false))
  }
  const release = () => post(`/api/companies/${companyId}/audit/working-file/release`).catch(() => setMsg({ kind: 'error', text: t('file.blocked_release') }))
  if (!f) {
    return (
      <Panel title={t('file.title')} id="audit-file">
        <Stepper status="not_started" lang={lang} />
        <Empty icon="file" title={pick(data.working_file_empty, lang)} action={data.can.run_review && <Button variant="secondary" onClick={prepare} disabled={busy}>{t('file.prepare')}</Button>} />
        {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      </Panel>
    )
  }
  const open = f.gaps.filter((g) => g.status !== 'received')
  return (
    <Panel title={t('file.title')} id="audit-file" className="aud-file">
      <Stepper status={f.status} lang={lang} />
      <div className="aud-file-head">
        <p><strong>{t('file.label', { status: pick(f.status_label, lang) })}</strong></p>
        <div className="aud-labels">
          <Chip tone={f.completeness_state === 'incomplete' ? 'attention' : 'info'}>{t(`file.completeness.${f.completeness_state}`)}</Chip>
          {f.out_of_date && <Chip tone="neutral" icon="↻">{t('file.out_of_date')}</Chip>}
          {f.is_demo && <Chip tone="neutral">{t('demo')}</Chip>}
        </div>
        <p className="helper">{t('file.complete_note')}</p>
        {f.engagement && <p className="muted">{t('file.engagement', { em: f.engagement.engagement_manager_role, team: f.engagement.preparing_team_role })}</p>}
      </div>
      {f.return && (
        <div className="aud-note" role="status">
          <h3>{t('file.rejected_heading')}</h3>
          <p>{formatDateTime(f.return.at, lang)} · {t(`file.reason_codes.${f.return.reason_code}`)}</p>
          {f.return.free_text && <p lang={f.return.reason_language}>{f.return.free_text} <span className="muted">({t('file.not_translated')})</span></p>}
          <p>{t('file.rejected_next')}</p>
          <Link to="/help">{t('exceptions.escalate')}</Link>
        </div>
      )}
      {f.out_of_date && <Message kind="warning">{t('file.out_of_date_banner', { date: formatDate(f.changed_on, lang), name: f.changed_by })}</Message>}
      {f.completeness_state === 'incomplete' && <Message kind="info">{t('file.incomplete', { n: open.length, m: f.gaps.length })}</Message>}
      {f.review_recorded && <Message kind="info">{pick(f.review_recorded.text, lang)}{f.review_recorded.supplied_documents_only && <><br />{t('file.supplied_only')}</>}</Message>}
      {f.signed_outside && <Message kind="info">{pick(f.signed_outside.text, lang)} <Chip tone="neutral">{pick(f.signed_outside.badge, lang)}</Chip></Message>}
      <div className="aud-file-cols">
      <div>
      <h3 className="aud-sub">{t('file.gaps', { n: open.length })} <span className="muted">· {t('file.gaps_summary', { n: f.gaps_summary.complete, m: f.gaps_summary.total })}</span></h3>
      <ul className="aud-checklist aud-gaps">
        {f.gaps.map((g) => (
          <li key={g.id}>
            <span className={`aud-check-icon ${g.status === 'received' ? 'aud-check-done' : 'aud-check-open'}`} aria-hidden="true"><Icon name={g.status === 'received' ? 'check' : g.status === 'overdue' ? 'alert' : 'clock'} size={16} /></span>
            <div className="aud-item-main">
              <div className="aud-gap-title"><span className="muted nowrap">{t('file.gap_n', { n: g.gap_number })}</span> <span>{pick(g.item, lang)}</span></div>
              <div className="hint">{pick(g.why, lang)}</div>
            </div>
            <div className="aud-gap-side">
              <Chip tone={g.status === 'overdue' ? 'urgent' : g.status === 'received' ? 'ok' : 'attention'}>{t(`file.gap_status.${g.status}`)}</Chip>
              <span className="aud-gap-action">{g.action === 'add_statements' ? <Link to="/consent">{t(`file.gap_action.${g.action}`)}</Link> : t(`file.gap_action.${g.action}`)}</span>
            </div>
          </li>
        ))}
      </ul>
      </div>
      <div className="card aud-draft">
        <div aria-hidden="true" className="aud-draft-mark">
          <div dir="ltr" lang="en">{f.watermark.en}</div><div dir="rtl" lang="ar">{f.watermark.ar}</div>
        </div>
        <p className="watermark"><span lang="en" dir="ltr">{f.watermark.en}</span> / <span lang="ar" dir="rtl">{f.watermark.ar}</span></p>
        <p>{pick(f.page1_notice, lang)}</p>
        <h3 className="aud-sub">{t('file.figures')}</h3>
        <dl className="kv aud-figs">
          {(f.ai_prepared_content.figures ?? []).map((x) => <div key={x.key} style={{ display: 'contents' }}><dt>{pick(x.label, lang)}</dt><dd>{x.value_fils != null ? <bdi dir="ltr" className="num">{formatAED(x.value_fils, lang)}</bdi> : <Chip tone="attention">{t('file.gap_n', { n: x.gap ?? '?' })}</Chip>}</dd></div>)}
        </dl>
        {f.human_approved_content && <p className="muted">{t('file.human')}: {t('file.reviewer', { name: f.reviewer_name })}</p>}
        <p className="helper">{t('file.watermark_note')}</p>
      </div>
      </div>
      <div className="actions">
        {data.can.download ? (f.out_of_date ? <Button variant="secondary" aria-disabled="true" disabled>{t('file.export')}</Button> : <a className="btn btn-secondary" href={`/api/companies/${companyId}/audit/working-file/export?lang=${lang}`} target="_blank" rel="noreferrer"><Icon name="external" size={16} />{t('file.export')}</a>) : <p className="muted">{pick(data.download_note, lang) || t('file.download_hidden')}</p>}
        {data.can.run_review && <Button variant="secondary" onClick={prepare} disabled={busy}>{t('file.prepare')}</Button>}
        <Button variant="secondary" aria-disabled="true" onClick={release} title={t('file.blocked_release')}>{t('file.release')}</Button>
      </div>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <Disclosure summary={t('file.history')}>
        <ol className="timeline">
          {f.history.map((h, i) => <li key={i} style={h.invalid ? { textDecoration: 'line-through' } : undefined}><span>{h.to}</span><span>{h.who}</span><span className="nowrap">{formatDateTime(h.at, lang)}</span>{h.invalid && <span>{t('file.invalid', { date: formatDate(h.invalid_since, lang) })}</span>}</li>)}
        </ol>
      </Disclosure>
    </Panel>
  )
}
