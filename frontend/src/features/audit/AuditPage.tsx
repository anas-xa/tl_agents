import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Empty, Field, Ident, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatAED, formatDate, formatDateTime } from '../../lib/format'
import type { AuditOverview, Bi, FlagDetail, FlagRow, Indicator, WorkingFile } from './types'

const pick = (b: Bi | null | undefined, lang: string) => (b ? (lang === 'ar' ? b.ar : b.en) : '')
const SEV_TONE = { High: 'urgent', Medium: 'attention', Low: 'neutral' } as const
const STATUS_TONE = { New: 'info', Confirmed: 'ok', Explained: 'neutral', Dismissed: 'neutral', Escalated: 'attention' } as const
const STATE_TONE = { likely_required: 'attention', likely_not_required: 'neutral', cannot_determine: 'info', not_yet_assessed: 'neutral' } as const

/** SC8 Audit preparation status: indicator card, items for review, audit work draft. */
export default function AuditPage() {
  const { t, i18n } = useTranslation('audit')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { companyId } = useAuth()
  const [data, setData] = useState<AuditOverview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => {
    if (!companyId) return
    get<AuditOverview>(`/api/companies/${companyId}/audit`).then((d) => { setData(d); setErr(null) }).catch((e: ApiError) => setErr(e.code))
  }, [companyId])
  useEffect(() => { load() }, [load])
  if (err && !data) return <div><h1>{t('title')}</h1><Message kind="error">{t('error')} <Button variant="link" onClick={load}>{t('indicator.try_again')}</Button></Message></div>
  if (!data) return <div><h1>{t('title')}</h1><p aria-busy="true">{t('indicator.loading')}</p><Skeleton rows={6} /></div>
  return (
    <div>
      <h1>{t('title')}</h1>
      <IndicatorCard data={data} lang={lang} companyId={companyId!} onChange={load} />
      <ExceptionsSection data={data} lang={lang} companyId={companyId!} onChange={load} />
      <WorkingFileSection data={data} lang={lang} companyId={companyId!} onChange={load} />
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
    <Panel title={t('indicator.title')} id="audit-indicator">
      <p><Chip tone="info" icon="ⓘ">{text.badge_indicative}</Chip> {f.is_demo && <Chip tone="neutral">{t('demo')}</Chip>}</p>
      <h3 ref={headingRef} tabIndex={-1}>
        <Chip tone={STATE_TONE[f.state]}>{t(`indicator.states.${f.state}`)}</Chip> {headline}
      </h3>
      {f.not_refreshed && <Message kind="warning">{t('indicator.not_refreshed', { date: formatDateTime(f.evaluated_at, lang) })} <Button variant="link" onClick={() => post(`/api/companies/${companyId}/audit/flag/recompute`).then(onChange)}>{t('indicator.try_again')}</Button></Message>}
      {f.case && <div className="card" role="status"><p>{f.near_threshold ? t('indicator.case_strip') : t('indicator.person')}</p><p className="muted">{f.case.status} · {formatDate(f.case.opened_at, lang)} · <Link to="/help">{t('indicator.case_open')}</Link></p></div>}
      {f.change_notice && !f.banner_hidden && (
        <div role="status" className="card">
          <p>{t('indicator.change_notice', { old: t(`indicator.states.${f.previous_result}`), new: t(`indicator.states.${f.state}`) })}</p>
          {!readOnly && <Button variant="secondary" onClick={() => act('acknowledge')}>{t('indicator.got_it')}</Button>}
        </div>
      )}
      {['may_be_required', 'not_indicated_detail', 'shown_because_revenue', 'near_threshold_strip', 'at_threshold', 'caveat_revenue_only'].filter((k) => text[k]).map((k) => <p key={k}>{text[k]}</p>)}
      {f.state === 'cannot_determine' && (f.checklist?.length ?? 0) > 0 && (
        <div>
          <p>{t('indicator.checklist')}</p>
          <ul>{f.checklist!.map((c) => <li key={c.item}><Chip tone="attention">{t('indicator.missing')}</Chip> {lang === 'ar' ? c.ar : c.en}{c.gloss_en && <span className="muted"> — {lang === 'ar' ? c.gloss_ar : c.gloss_en}</span>}</li>)}</ul>
        </div>
      )}
      <details>
        <summary>{t('indicator.why')}</summary>
        {(f.cannot_determine_reasons?.length ?? 0) > 0 && <ul>{f.cannot_determine_reasons!.map((r) => <li key={r}>{t(`indicator.reasons.${r}`)}</li>)}</ul>}
        {f.period_start && <p>{t('indicator.period', { start: formatDate(f.period_start, lang), end: formatDate(f.period_end, lang) })}</p>}
        {f.revenue_source && <p>{t('indicator.source', { source: t(`indicator.sources.${f.revenue_source}`) })}</p>}
        {f.twelve_month_equivalent_fils != null && <p>{t('indicator.equivalent', { amount: formatAED(f.twelve_month_equivalent_fils, lang) })}</p>}
        {f.criteria_version && <p className="muted">{t('indicator.criteria', { v: f.criteria_version, instrument: f.instrument })}</p>}
        <p className="helper">{text.disclaimer_basis}</p>
      </details>
      {text.next_steps && <p>{text.next_steps} {text.free_choice}</p>}
      <p className="helper">{text.disclaimer}</p>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      {readOnly ? <p className="muted">{pick(data.read_only_note, lang) || t('indicator.read_only')}</p> : f.state !== 'not_yet_assessed' && (
        <div className="actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {f.change_notice && !f.banner_hidden && data.can.hide_banner && <Button variant="secondary" onClick={() => act('hide_banner')}>{t('indicator.hide')}</Button>}
          {data.can.dispute && <Button variant="secondary" onClick={() => setDisputeOpen(!disputeOpen)} aria-expanded={disputeOpen}>{t('indicator.dispute')}</Button>}
          {data.can.request_review && <Button variant="secondary" onClick={() => act('request_review')}>{t('indicator.request_review')}</Button>}
          <Button variant="link" aria-disabled="true" title={t('indicator.ask_auditor_off')} onClick={() => setMsg({ kind: 'info', text: t('indicator.ask_auditor_off') })}>{t('indicator.ask_auditor')}</Button>
        </div>
      )}
      {disputeOpen && (
        <form onSubmit={(e) => { e.preventDefault(); act('dispute', { reason_code: code, reason: note || undefined }) }}>
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
  if (data.exceptions === null) return <Panel title={t('exceptions.title')} id="audit-exceptions"><p>{pick(data.exceptions_hidden_reason, lang)}</p></Panel>
  const rows = data.exceptions.filter((r) => (!sev || r.severity === sev) && (!status || r.status === status))
  const rv = data.review
  const run = () => { setRunning(true); post(`/api/companies/${companyId}/audit/review/run`).finally(() => { setRunning(false); onChange() }) }
  if (sel) return <FlagDetailPanel id={sel} data={data} lang={lang} companyId={companyId} onBack={() => { setSel(null); onChange() }} />
  return (
    <Panel title={t('exceptions.title')} id="audit-exceptions" actions={data.can.run_review && <Button variant="secondary" onClick={run} disabled={running}>{t('exceptions.run')}</Button>}>
      <p className="helper">{t('flag_prompt')}</p>
      {running && <p role="status">{t('exceptions.in_progress', { date: formatDateTime(rv?.last_cycle_at, lang) })}</p>}
      {rv?.last_cycle_at && <p className="muted">{t('exceptions.last_review', { date: formatDateTime(rv.last_cycle_at, lang), sources: rv.sources_read.map((s) => t(`exceptions.source.${s}`)).join(', ') || '—' })}</p>}
      {rv?.more_available && <Message kind="info">{t('exceptions.more_available')}</Message>}
      {rv?.empty_state === 'consent_withdrawn' && <Message kind="warning">{t('exceptions.empty_c', { date: formatDate(rv.ended_on, lang) })} <Link to="/consent">{t('exceptions.open_consent')}</Link></Message>}
      {data.exceptions.length === 0 ? (
        rv?.empty_state === 'no_source' ? <Empty title={t('exceptions.empty_b')} action={<><Link className="btn btn-primary" to="/consent">{t('exceptions.connect')}</Link> <span className="muted">{t('exceptions.manual')}</span></>} />
          : rv?.empty_state === 'no_review_yet' ? <Empty title={t('exceptions.no_review_yet')} /> : rv?.empty_state === 'consent_withdrawn' ? null : <Empty title={t('exceptions.empty_a')} body={rv?.last_cycle_at ? formatDateTime(rv.last_cycle_at, lang) : undefined} />
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <label>{t('exceptions.cols.severity')} <select value={sev} onChange={(e) => setSev(e.target.value)}><option value="">{t('exceptions.severity.all')}</option>{['High', 'Medium', 'Low'].map((s) => <option key={s} value={s}>{t(`exceptions.severity.${s}`)}</option>)}</select></label>
            <label>{t('exceptions.cols.status')} <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t('exceptions.status.all')}</option>{['New', 'Confirmed', 'Explained', 'Dismissed', 'Escalated'].map((s) => <option key={s} value={s}>{t(`exceptions.status.${s}`)}</option>)}</select></label>
          </div>
          {rows.length === 0 ? <Empty title={t('exceptions.empty_d')} action={<Button variant="secondary" onClick={() => { setSev(''); setStatus('') }}>{t('exceptions.clear_filters')}</Button>} /> : (
            <Table headers={[t('exceptions.cols.rule'), t('exceptions.cols.severity'), t('exceptions.cols.status'), t('exceptions.cols.source'), t('exceptions.cols.amount'), t('exceptions.cols.flagged')]}>
              {rows.map((r: FlagRow) => (
                <tr key={r.id}>
                  <td><button type="button" className="btn btn-link" onClick={() => setSel(r.id)}>{pick(r.rule_title, lang)}</button><br /><Chip tone="draft" icon="✎">{pick(r.ai_label, lang)}</Chip>{r.is_demo && <> <Chip tone="neutral">{t('demo')}</Chip></>}{r.evidence_changed_since && <> <Chip tone="attention" icon="!">{t('exceptions.evidence_changed', { date: formatDate(r.evidence_changed_since, lang) })}</Chip></>}</td>
                  <td><Chip tone={SEV_TONE[r.severity]}>{t(`exceptions.severity.${r.severity}`)}</Chip></td>
                  <td><Chip tone={STATUS_TONE[r.status]}>{t(`exceptions.status.${r.status}`)}</Chip></td>
                  <td>{t(`exceptions.source.${r.source}`, { defaultValue: r.source })}{r.source_withdrawn && <> <Chip tone="neutral" icon="🔒">{t('exceptions.hidden_row')}</Chip></>}</td>
                  <td>{r.amount_fils != null ? <bdi dir="ltr">{formatAED(r.amount_fils, lang)}</bdi> : '—'}</td>
                  <td>{formatDate(r.flagged_at, lang)}</td>
                </tr>
              ))}
            </Table>
          )}
        </>
      )}
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
      <p><Chip tone="draft" icon="✎">{pick(d.ai_label, lang)}</Chip> <Chip tone={SEV_TONE[d.severity]}>{t(`exceptions.severity.${d.severity}`)}</Chip> <Chip tone={STATUS_TONE[d.status]}>{t(`exceptions.status.${d.status}`)}</Chip></p>
      <p className="muted">{t('exceptions.triggered_by', { name: d.rule_id, n: d.rule_version })}{d.rule_label && ` · ${t('exceptions.cash_label')}`}</p>
      <p className="helper">{t('flag_prompt')}</p>
      {d.source_withdrawn && <Message kind="info">{t('exceptions.source_withdrawn')}</Message>}
      {d.based_on_data_up_to && <p className="muted">{t('exceptions.based_on', { date: formatDate(d.based_on_data_up_to, lang) })}</p>}
      {d.evidence_changed_since && <Message kind="warning">{t('exceptions.evidence_changed', { date: formatDate(d.evidence_changed_since, lang) })}</Message>}
      <h3>{t('exceptions.evidence')}</h3>
      <Table headers={[t('exceptions.evidence_cols.record'), t('exceptions.evidence_cols.date'), t('exceptions.evidence_cols.amount'), t('exceptions.evidence_cols.counterparty'), t('exceptions.evidence_cols.reference')]}>
        {d.evidence.map((r) => r.masked ? (
          <tr key={r.record_id} aria-label={t('exceptions.hidden_row_name')}><td><Ident>{r.record_id}</Ident></td><td>{formatDate(r.date, lang)}</td><td colSpan={3}><span aria-hidden="true">🔒 </span>{t('exceptions.hidden_row')}</td></tr>
        ) : (
          <tr key={r.record_id}><td><Ident>{r.record_id}</Ident></td><td>{formatDate(r.date, lang)}</td><td><bdi dir="ltr">{formatAED(r.amount_fils ?? null, lang)}</bdi></td><td><bdi>{r.counterparty ?? '—'}</bdi></td><td><Ident>{r.invoice_number ?? r.account_code ?? '—'}</Ident></td></tr>
        ))}
      </Table>
      {d.revisions.length > 1 && (
        <details><summary>{t('exceptions.see_changes')}</summary>
          <ol className="timeline">{d.revisions.map((r) => <li key={r.revision_no}><span>#{r.revision_no}</span><span>{formatDateTime(r.created_at, lang)}</span><span>{r.actor}</span><span>{r.change_summary}</span></li>)}</ol>
        </details>
      )}
      <h3>{t('exceptions.decision')}</h3>
      {!canDecide && <p id="no-right" className="helper">{pick(data.decide_disabled_reason, lang) || t('exceptions.no_right')}</p>}
      <form onSubmit={save} aria-describedby={!canDecide ? 'no-right' : undefined}>
        <fieldset aria-disabled={!canDecide}>
          {['confirm', 'explain', 'dismiss'].map((k) => (
            <label key={k} style={{ display: 'block', minHeight: 44 }}><input type="radio" name="decision" value={k} checked={decision === k} onChange={() => canDecide && setDecision(k)} aria-disabled={!canDecide} /> {t(`exceptions.${k}`)}</label>
          ))}
        </fieldset>
        <Field label={t('exceptions.reason')} id="decision-reason" hint={t('exceptions.counter', { n: reason.trim().length })}>
          <textarea id="decision-reason" value={reason} onChange={(e) => setReason(e.target.value)} readOnly={!canDecide} aria-disabled={!canDecide} />
        </Field>
        <Button type="submit" aria-disabled={!canDecide || !decision || reason.trim().length < 10} disabled={!canDecide || !decision || reason.trim().length < 10}>{t('exceptions.save')}</Button>
        {data.can.escalate && canDecide && <> <Button type="button" variant="secondary" onClick={escalate}>{t('exceptions.escalate')}</Button></>}
      </form>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <h3 ref={historyRef} tabIndex={-1}>{t('exceptions.history')}</h3>
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
    <ol aria-label={t('file.stepper')} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', listStyle: 'none', padding: 0 }} lang={lang}>
      {steps.map((s, i) => {
        const current = s === status
        const unavailable = s === 'signed'
        return (
          <li key={s} aria-current={current ? 'step' : undefined} aria-label={`${t('file.step_of', { n: i + 1, m: steps.length, name: t(`file.steps.${s}`) })}${current ? `, ${t('file.current')}` : ''}${unavailable ? `, ${t('file.signing_na')}` : ''}`}>
            <Chip tone={current ? 'info' : 'neutral'} icon={current ? '●' : '○'}>{t(`file.steps.${s}`)}{unavailable && <span className="muted"> ({t('file.signing_na')})</span>}</Chip>
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
  if (data.working_file_hidden) return <Panel title={t('file.title')} id="audit-file"><p>{pick(data.working_file_hidden, lang)}</p></Panel>
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
        <Empty title={pick(data.working_file_empty, lang)} action={data.can.run_review && <Button variant="secondary" onClick={prepare} disabled={busy}>{t('file.prepare')}</Button>} />
        {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      </Panel>
    )
  }
  const open = f.gaps.filter((g) => g.status !== 'received')
  return (
    <Panel title={t('file.title')} id="audit-file">
      <Stepper status={f.status} lang={lang} />
      <p><strong>{t('file.label', { status: pick(f.status_label, lang) })}</strong> {f.is_demo && <Chip tone="neutral">{t('demo')}</Chip>}</p>
      <p><Chip tone={f.completeness_state === 'incomplete' ? 'attention' : 'info'}>{t(`file.completeness.${f.completeness_state}`)}</Chip> {f.out_of_date && <Chip tone="neutral" icon="↻">{t('file.out_of_date')}</Chip>}</p>
      <p className="helper">{t('file.complete_note')}</p>
      {f.engagement && <p className="muted">{t('file.engagement', { em: f.engagement.engagement_manager_role, team: f.engagement.preparing_team_role })}</p>}
      {f.return && (
        <div className="card" role="status">
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
      <details open={open.length > 0}>
        <summary>{t('file.gaps', { n: open.length })} · {t('file.gaps_summary', { n: f.gaps_summary.complete, m: f.gaps_summary.total })}</summary>
        <Table headers={[t('file.gap_cols.n'), t('file.gap_cols.item'), t('file.gap_cols.why'), t('file.gap_cols.status'), t('file.gap_cols.action')]}>
          {f.gaps.map((g) => (
            <tr key={g.id}><td>{t('file.gap_n', { n: g.gap_number })}</td><td>{pick(g.item, lang)}</td><td>{pick(g.why, lang)}</td><td><Chip tone={g.status === 'overdue' ? 'urgent' : g.status === 'received' ? 'ok' : 'attention'}>{t(`file.gap_status.${g.status}`)}</Chip></td><td>{g.action === 'add_statements' ? <Link to="/consent">{t(`file.gap_action.${g.action}`)}</Link> : t(`file.gap_action.${g.action}`)}</td></tr>
          ))}
        </Table>
      </details>
      <div className="card" style={{ position: 'relative', overflow: 'hidden' }}>
        <div aria-hidden="true" style={{ position: 'absolute', insetInlineStart: 0, insetInlineEnd: 0, top: '40%', textAlign: 'center', transform: 'rotate(-30deg)', opacity: 0.15, fontSize: '1.6rem', fontWeight: 800, pointerEvents: 'none' }}>
          <div dir="ltr" lang="en">{f.watermark.en}</div><div dir="rtl" lang="ar">{f.watermark.ar}</div>
        </div>
        <p className="watermark"><span lang="en" dir="ltr">{f.watermark.en}</span> / <span lang="ar" dir="rtl">{f.watermark.ar}</span></p>
        <p>{pick(f.page1_notice, lang)}</p>
        <h3>{t('file.figures')}</h3>
        <dl className="kv">
          {(f.ai_prepared_content.figures ?? []).map((x) => <div key={x.key} style={{ display: 'contents' }}><dt>{pick(x.label, lang)}</dt><dd>{x.value_fils != null ? <bdi dir="ltr">{formatAED(x.value_fils, lang)}</bdi> : <Chip tone="attention">{t('file.gap_n', { n: x.gap ?? '?' })}</Chip>}</dd></div>)}
        </dl>
        {f.human_approved_content && <p className="muted">{t('file.human')}: {t('file.reviewer', { name: f.reviewer_name })}</p>}
        <p className="helper">{t('file.watermark_note')}</p>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
        {data.can.download ? (f.out_of_date ? <Button variant="secondary" aria-disabled="true" disabled>{t('file.export')}</Button> : <a className="btn btn-secondary" href={`/api/companies/${companyId}/audit/working-file/export?lang=${lang}`} target="_blank" rel="noreferrer">{t('file.export')}</a>) : <p className="muted">{pick(data.download_note, lang) || t('file.download_hidden')}</p>}
        {data.can.run_review && <Button variant="secondary" onClick={prepare} disabled={busy}>{t('file.prepare')}</Button>}
        <Button variant="secondary" aria-disabled="true" onClick={release} title={t('file.blocked_release')}>{t('file.release')}</Button>
      </div>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <h3>{t('file.history')}</h3>
      <ol className="timeline">
        {f.history.map((h, i) => <li key={i} style={h.invalid ? { textDecoration: 'line-through' } : undefined}><span>{h.to}</span><span>{h.who}</span><span>{formatDateTime(h.at, lang)}</span>{h.invalid && <span>{t('file.invalid', { date: formatDate(h.invalid_since, lang) })}</span>}</li>)}
      </ol>
    </Panel>
  )
}
