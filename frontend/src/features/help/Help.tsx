import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Slot, useSlotEntries } from '../../components/Slot'
import { AiLabel, Button, Chip, Empty, Field, Ident, Message, PageHeader, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import './help.css'

type Bi = { en: string; ar: string }
interface CaseView {
  case_id: string; module: string; status: string; handler_type: 'licensed_human' | 'ai_draft'; priority: string; escalation_reason: string; title: string | null
  due_date: string | null; opened_at: string; resolved_at: string | null; closed_at: string | null; case_owner_role: string; assigned: boolean; assigned_role_label: string | null
  linked_case_id: string | null; consent_needed: boolean; consent_decision: string | null; requested_scope: { module: string; data_class: string; period_from?: string; period_to?: string }[]
  waiting_for_you: boolean; required_action: string | null; reject: { reason_code: string; note: string | null } | null; resolution_outcome: string | null; resolution_limitation: boolean
  output_label: Bi | null; closed_no_consent: boolean; reopen_until: string | null; legal_route_status: string | null; flags: string[]; is_demo: boolean; read_only: boolean
  activity: { type: string; at: string; reason_code: string | null }[]; access_log?: { who: string; role: string; what: string; when: string; result: string; reason: string | null }[]
}
interface CaseList { can_reject: boolean; cases: CaseView[] }
interface Citation { passage_id: string; instrument: string; instrument_ar: string; article: string; corpus_version: string; effective_from: string | null; quoted_text_ar: string; text_en_unofficial: string; source_ref: string | null }
interface Answer {
  question_id: string; decision: string; language: string; body: Bi; citations: Citation[]; case_id: string | null; escalation_status?: string; review_band?: boolean
  general_rule?: { body: Bi; citations: Citation[] } | null; value_status?: string
}

const STATUS_TONE: Record<string, { tone: 'neutral' | 'ok' | 'attention' | 'urgent' | 'critical' | 'info' | 'draft'; icon: string }> = {
  open: { tone: 'info', icon: '○' }, awaiting_consent: { tone: 'attention', icon: '◔' }, with_specialist: { tone: 'info', icon: '☺' }, rejected: { tone: 'neutral', icon: '✕' }, resolved: { tone: 'ok', icon: '✓' }, closed: { tone: 'neutral', icon: '▢' },
}

function StatusChip({ status }: { status: string }) {
  const { t } = useTranslation('help')
  const s = STATUS_TONE[status] ?? STATUS_TONE.open
  return <Chip tone={s.tone} icon={s.icon}>{t(`status.${status}`)}</Chip>
}

/** SC10 Help and human escalation: label landmark first, then question box, case list, escalation form, help sections. */
export default function Help() {
  const { t, i18n } = useTranslation('help')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { companyId, company } = useAuth()
  const [list, setList] = useState<CaseList | null>(null)
  const [err, setErr] = useState<{ code: string; ref?: string } | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const load = useCallback(() => {
    if (!companyId) return
    setErr(null)
    get<CaseList>(`/api/companies/${companyId}/cases`).then(setList).catch((e: ApiError) => setErr({ code: e.code, ref: e.reference }))
  }, [companyId])
  useEffect(load, [load])
  const isOwner = !!company && (company.roles.includes('owner') || company.roles.includes('remote_owner'))
  const current = list?.cases.find((c) => c.case_id === selected) ?? null
  const sections = useSlotEntries('help.sections')

  return (
    <div className="help-page">
      <section role="region" aria-label={t('information_not_advice')} className="info-label help-label" tabIndex={-1}>
        <Chip tone="info" icon="i">{t('information_not_advice')}</Chip>
      </section>
      <PageHeader title={t('title')} subtitle={t('subtitle')} />
      <QuestionBox companyId={companyId} onCase={load} />
      {err?.code === 'NOT_YOUR_COMPANY' || err?.code === 'NO_PERMISSION' ? (
        <Message kind="error">{t('states.noAccess')}</Message>
      ) : err ? (
        <Message kind="error">{t('states.error')} {err.ref && <> {t('states.reference')}: <Ident>{err.ref}</Ident></>} <Button variant="link" onClick={load}>{t('qa.try_again')}</Button></Message>
      ) : null}
      {current ? (
        <CaseDetail c={current} canReject={!!list?.can_reject} isOwner={isOwner} companyId={companyId!} onBack={() => setSelected(null)} onChange={load} />
      ) : (
        <>
          <Panel title={t('list.title')} id="cases">
            {!list && !err ? (<><p aria-live="polite">{t('states.loading')}</p><Skeleton rows={3} /></>) : list && list.cases.length === 0 ? (
              <Empty icon="inbox" title={t('states.empty')} />
            ) : list ? (
              <ul className="help-cases">
                {list.cases.map((c) => (
                  <li key={c.case_id}>
                    <span className={`help-case-icon ${c.handler_type === 'licensed_human' ? 'is-human' : ''}`} aria-hidden="true"><Icon name={c.handler_type === 'licensed_human' ? 'user' : 'sparkle'} size={16} /></span>
                    <div className="help-case-main">
                      <div className="help-case-title">
                        <button type="button" className="help-case-link" onClick={() => setSelected(c.case_id)}>
                          {c.title ?? t(`form.modules.${c.module}`)}
                        </button>
                        <Ident>{c.case_id.slice(0, 13)}</Ident>
                      </div>
                      <div className="help-case-meta">
                        <span>{t('list.owner_role')}: {t(`queue.${c.case_owner_role}`)}</span>
                        <span className="nowrap">{t('list.date')}: {formatDate(c.opened_at, lang)}</span>
                      </div>
                    </div>
                    <div className="help-case-chips">
                      <StatusChip status={c.status} />
                      {c.waiting_for_you && <Chip tone="attention" icon="◔">{t('status.waiting_for_you')}</Chip>}
                      <Chip tone={c.handler_type === 'licensed_human' ? 'ok' : 'draft'} icon={c.handler_type === 'licensed_human' ? '☺' : '✎'}><span className="visually-hidden">{t('handled_by')}: </span>{t(`handler.${c.handler_type}`)}</Chip>
                      {c.linked_case_id && <Chip tone="neutral" icon="⇄">{t('list.linked')}</Chip>}
                      {c.is_demo && <Chip tone="draft" icon="▭">{t('list.demo')}</Chip>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}
          </Panel>
          <EscalationForm companyId={companyId} onCreated={load} />
        </>
      )}
      {sections.length > 0 && (
        <Panel title={t('sections')} id="help-sections">
          <Slot name="help.sections" />
        </Panel>
      )}
    </div>
  )
}

function EscalationForm({ companyId, onCreated }: { companyId: string | null; onCreated: () => void }) {
  const { t } = useTranslation('help')
  const [module, setModule] = useState('tax')
  const [title, setTitle] = useState('')
  const [linked, setLinked] = useState('')
  const [topic, setTopic] = useState('vat_general')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const shared = t('form.shared', { returnObjects: true }) as string[]
  const notShared = t('form.not_shared', { returnObjects: true }) as string[]
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!companyId) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await post<{ status?: string; case_id?: string }>(`/api/companies/${companyId}/cases`, { module, title: module === 'legal' ? null : title || null, linked_item_id: linked || null, topic_code: linked ? null : topic })
      setMsg(r.status === 'setting_up' ? t('states.setup') : null)
      setTitle('')
      setLinked('')
      onCreated()
    } catch (e2) {
      setMsg((e2 as ApiError).code === 'NO_PERMISSION' ? t('states.noAccess') : t('states.error'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel title={t('form.title')} id="ask-human">
      <p>{t('form.intro')}</p>
      <form onSubmit={submit} className="help-form">
        <Field label={t('form.module')} id="esc-module">
          <select id="esc-module" value={module} onChange={(e) => setModule(e.target.value)}>
            {['tax', 'audit', 'compliance', 'legal'].map((m) => <option key={m} value={m}>{t(`form.modules.${m}`)}</option>)}
          </select>
        </Field>
        {module === 'legal' ? (
          <div className="help-wide"><Message kind="info">{t('form.legal_note')} {t('no_route')}</Message></div>
        ) : (
          <>
            <Field label={t('form.linked')} id="esc-linked"><input id="esc-linked" value={linked} onChange={(e) => setLinked(e.target.value)} dir="ltr" /></Field>
            {!linked && (
              <Field label={t('form.topic')} id="esc-topic">
                <select id="esc-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
                  {['vat_general', 'corporate_tax_general', 'audit_general', 'licence_general', 'other'].map((k) => <option key={k} value={k}>{t(`form.topics.${k}`)}</option>)}
                </select>
              </Field>
            )}
            <Field label={t('form.your_title')} id="esc-title"><input id="esc-title" maxLength={255} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          </>
        )}
        <div className="help-share help-wide">
          <div>
            <h3>{t('form.shared_title')}</h3>
            <ul className="help-checks">{shared.map((s) => <li key={s}><span className="help-check is-yes" aria-hidden="true"><Icon name="check" size={12} /></span>{s}</li>)}</ul>
          </div>
          <div>
            <h3>{t('form.not_shared_title')}</h3>
            <ul className="help-checks">{notShared.map((s) => <li key={s}><span className="help-check is-no" aria-hidden="true"><Icon name="lock" size={12} /></span>{s}</li>)}</ul>
          </div>
        </div>
        <p className="hint help-wide">{t('form.no_timing')}</p>
        {msg && <div className="help-wide"><Message kind="info">{msg}</Message></div>}
        <div className="help-wide"><Button type="submit" disabled={busy}>{busy ? t('form.sending') : t('form.submit')}</Button></div>
      </form>
    </Panel>
  )
}

function CaseDetail({ c, canReject, isOwner, companyId, onBack, onChange }: { c: CaseView; canReject: boolean; isOwner: boolean; companyId: string; onBack: () => void; onChange: () => void }) {
  const { t, i18n } = useTranslation('help')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [formErr, setFormErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [answerRef, setAnswerRef] = useState('')
  const reasonRef = useRef<HTMLSelectElement>(null)
  useEffect(() => { if (rejecting) reasonRef.current?.focus() }, [rejecting])
  const act = async (path: string, body?: unknown, done?: string) => {
    setFormErr(null)
    try {
      await post(`/api/companies/${companyId}/cases/${c.case_id}/${path}`, body)
      setMsg(done ?? null)
      onChange()
    } catch (e) {
      const err = e as ApiError
      setFormErr(err.code === 'ONLY_OWNER_CAN_REJECT' ? t('reject.only_owner') : err.code === 'REJECT_NOTE_REQUIRED' ? t('reject.note_required') : err.code === 'REJECT_REASON_REQUIRED' ? t('reject.choose') : err.message)
    }
  }
  const reject = (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason) { setFormErr(t('reject.choose')); reasonRef.current?.focus(); return }
    if (reason === 'R5' && !note.trim()) { setFormErr(t('reject.note_required')); return }
    act('reject', { reason_code: reason, note: note || null }, t('reject.done')).then(() => setRejecting(false))
  }
  const nextKey = ['tax', 'audit', 'compliance'].includes(c.module) ? `next_step.${c.module}` : 'no_route'
  return (
    <Panel title={<>{c.title ?? t(`form.modules.${c.module}`)} <Ident>{c.case_id}</Ident></>} id="case-detail" actions={<Button variant="secondary" onClick={onBack}>{t('detail.back')}</Button>}>
      <p><StatusChip status={c.status} /> {c.waiting_for_you && <Chip tone="attention" icon="◔">{t('status.waiting_for_you')}</Chip>} <Chip tone={c.handler_type === 'licensed_human' ? 'ok' : 'draft'} icon={c.handler_type === 'licensed_human' ? '☺' : '✎'}>{t('handled_by')}: {t(`handler.${c.handler_type}`)}</Chip> {c.handler_type === 'ai_draft' && <AiLabel />}</p>
      {msg && <Message kind="success">{msg}</Message>}
      <p><strong>{t('detail.next')}</strong> ({t(`queue.${c.case_owner_role}`)}{c.assigned_role_label ? ` · ${c.assigned_role_label}` : ''}): {t(nextKey)}</p>
      {c.module === 'legal' && <Message kind="info"><Chip tone="info" icon="i">{t('qa.legal_label')}</Chip> {t('qa.legal')} {t('qa.legal_own_choice')}</Message>}
      {c.linked_case_id && <p><Chip tone="neutral" icon="⇄">{t('list.linked')}</Chip> <Ident>{c.linked_case_id}</Ident></p>}
      {c.due_date && <p>{t('form.modules.compliance')}: {formatDate(c.due_date, lang)}</p>}
      {c.consent_needed && (
        <Message kind="warning">
          <p>{t('consent.needed')}</p>
          {c.requested_scope.length > 0 && <p>{t('consent.requested')}: {c.requested_scope.map((s) => `${s.data_class}${s.period_from ? ` (${formatDate(s.period_from, lang)} – ${formatDate(s.period_to, lang)})` : ''}`).join(', ')}</p>}
          <p className="hint">{t('consent.expires', { days: 90 })}</p>
          <div className="actions">
            <Link to="/consent" className="btn btn-secondary">{t('consent.review')}</Link>
            <Button disabled={!isOwner} aria-disabled={!isOwner} title={isOwner ? undefined : t('consent.only_owner')} onClick={() => act('consent', { decision: 'grant' })}>{t('consent.grant')}</Button>
            <Button variant="secondary" disabled={!isOwner} aria-disabled={!isOwner} title={isOwner ? undefined : t('consent.only_owner')} onClick={() => act('consent', { decision: 'refuse' })}>{t('consent.refuse')}</Button>
          </div>
          {!isOwner && <p className="hint">{t('consent.only_owner')}</p>}
          <p className="hint">{t('consent.refused_note')}</p>
        </Message>
      )}
      {c.consent_decision === 'granted' && !c.read_only && <div className="actions"><Button variant="danger" disabled={!isOwner} onClick={() => act('consent/revoke', undefined, t('consent.withdrawn'))}>{t('consent.revoke')}</Button></div>}
      {c.waiting_for_you && !c.read_only && (
        <form onSubmit={(e) => { e.preventDefault(); act('answer', { answer_ref: answerRef || null }).then(() => setAnswerRef('')) }}>
          <h3>{t('answer.title')}</h3>
          <p>{t('answer.waiting')} {c.required_action && <Ident>{c.required_action}</Ident>}</p>
          <Field label={t('answer.ref')} id="answer-ref"><input id="answer-ref" value={answerRef} onChange={(e) => setAnswerRef(e.target.value)} /></Field>
          <div className="actions"><Button type="submit">{t('answer.send')}</Button></div>
        </form>
      )}
      {c.resolution_outcome && <p><strong>{t('detail.outcome')}:</strong> {t(`detail.outcomes.${c.resolution_outcome}`)}</p>}
      {c.output_label && <Message kind="info"><strong>{t('detail.limitation')}:</strong> {c.output_label[lang]}</Message>}
      {c.closed_no_consent && (
        <Message kind="info">
          {t('detail.outcomes.d')}. {c.reopen_until && t('detail.reopen_until', { date: formatDate(c.reopen_until, lang) })}
          <div className="actions"><Button onClick={() => act('reopen')}>{t('reject.reopen_same')}</Button></div>
        </Message>
      )}
      {c.reject && <Message kind="info">{t('reject.done')} ({t(`reject.${c.reject.reason_code}`)})<div className="actions"><Button variant="secondary" onClick={() => act('reopen')}>{t('reject.reopen')}</Button></div></Message>}
      {c.read_only ? <p className="hint">{t('list.read_only')}</p> : (
        <div className="actions">
          {!rejecting && <Button variant="danger" disabled={!canReject} aria-disabled={!canReject} title={canReject ? undefined : t('reject.only_owner')} onClick={() => setRejecting(true)}>{t('reject.button')}</Button>}
          {!canReject && <span className="hint">{t('reject.only_owner')}</span>}
        </div>
      )}
      {rejecting && (
        <form onSubmit={reject} aria-describedby={formErr ? 'reject-err' : undefined}>
          <Field label={t('reject.reason')} id="reject-reason" required>
            <select id="reject-reason" ref={reasonRef} value={reason} onChange={(e) => setReason(e.target.value)} aria-invalid={!!formErr && !reason} aria-errormessage="reject-err">
              <option value="">—</option>
              {['R1', 'R2', 'R3', 'R4', 'R5'].map((r) => <option key={r} value={r}>{t(`reject.${r}`)}</option>)}
            </select>
          </Field>
          <Field label={t('reject.note')} id="reject-note" required={reason === 'R5'}><textarea id="reject-note" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          {formErr && <Message kind="error" id="reject-err">{formErr}</Message>}
          <div className="actions"><Button type="submit" variant="danger">{t('reject.button')}</Button><Button type="button" variant="secondary" onClick={() => setRejecting(false)}>{t('reject.cancel')}</Button></div>
        </form>
      )}
      {formErr && !rejecting && <Message kind="error">{formErr}</Message>}
      <h3>{t('detail.activity')}</h3>
      <ul>{c.activity.map((a, i) => <li key={i}>{formatDateTime(a.at, lang)} · {a.type.replace(/_/g, ' ')}{a.reason_code ? ` · ${a.reason_code}` : ''}</li>)}</ul>
      {c.access_log && (
        <>
          <h3>{t('detail.access_log')}</h3>
          {c.access_log.length === 0 ? <p>{t('detail.log_empty')}</p> : (
            <Table headers={['Who', 'What', 'When', 'Result']}>
              {c.access_log.map((r, i) => <tr key={i}><td><Ident>{r.who}</Ident> · {r.role}</td><td>{r.what}</td><td>{formatDateTime(r.when, lang)}</td><td><Chip tone={r.result === 'Allowed' ? 'ok' : 'critical'}>{r.result}{r.reason ? ` · ${r.reason}` : ''}</Chip></td></tr>)}
            </Table>
          )}
        </>
      )}
    </Panel>
  )
}

function CitationBlock({ c, lang }: { c: Citation; lang: string }) {
  const { t } = useTranslation('help')
  return (
    <div className="citation help-citation">
      <div className="help-citation-head"><Icon name="scale" size={16} /><span><bdi>{lang === 'ar' ? c.instrument_ar : c.instrument}</bdi> · <Ident>{c.article}</Ident></span></div>
      <dl className="kv help-citation-kv">
        <dt>{t('qa.instrument')}</dt><dd><bdi>{lang === 'ar' ? c.instrument_ar : c.instrument}</bdi></dd>
        <dt>{t('qa.article')}</dt><dd><Ident>{c.article}</Ident></dd>
        <dt>{t('qa.version')}</dt><dd><Ident>{c.corpus_version}</Ident></dd>
        <dt>{t('qa.effective')}</dt><dd>{formatDate(c.effective_from, lang)}</dd>
      </dl>
      <blockquote lang="ar" dir="rtl" className="help-quote">{c.quoted_text_ar}</blockquote>
      {lang !== 'ar' && <p className="hint" lang="en" dir="ltr">{t('qa.unofficial')} {c.text_en_unofficial}</p>}
    </div>
  )
}

function QuestionBox({ companyId, onCase }: { companyId: string | null; onCase: () => void }) {
  const { t, i18n } = useTranslation('help')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const [q, setQ] = useState('')
  const [urgent, setUrgent] = useState(false)
  const [state, setState] = useState<'empty' | 'loading' | 'slow' | 'error' | 'done'>('empty')
  const [ans, setAns] = useState<Answer | null>(null)
  const summary = useRef<HTMLParagraphElement>(null)
  const abort = useRef<AbortController | null>(null)
  const examples = t('qa.examples', { returnObjects: true }) as string[]
  const ask = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!companyId || !q.trim()) return
    setState('loading')
    setAns(null)
    const slow = window.setTimeout(() => setState((s) => (s === 'loading' ? 'slow' : s)), 10000)
    abort.current = new AbortController()
    try {
      const r = await post<Answer>(`/api/companies/${companyId}/ask`, { question: q, urgent })
      setAns(r)
      setState('done')
      if (r.case_id) onCase()
    } catch {
      setState('error')
    } finally {
      window.clearTimeout(slow)
      setTimeout(() => summary.current?.focus(), 0)
    }
  }
  const retry = async () => {
    if (!ans || !companyId) return
    await post(`/api/companies/${companyId}/ask/${ans.question_id}/retry`)
    ask()
  }
  const sendLegal = async () => {
    if (!companyId) return
    await post(`/api/companies/${companyId}/cases`, { module: 'legal', topic_code: 'legal_request' })
    onCase()
  }
  return (
    <section className="help-ask" id="qa" aria-labelledby="qa-title">
      <h2 id="qa-title" className="help-ask-title"><span className="help-ask-icon" aria-hidden="true"><Icon name="sparkle" size={18} /></span>{t('qa.title')}</h2>
      <p className="help-ask-intro">{t('qa.empty')}</p>
      <form onSubmit={ask}>
        <Field label={t('qa.placeholder')} id="qa-input">
          <textarea id="qa-input" value={q} onChange={(e) => setQ(e.target.value)} rows={2} dir="auto" />
        </Field>
        <div className="help-ask-row">
          <label className="checkbox"><input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} /> {t('qa.urgent')}</label>
          <div className="help-ask-actions">
            {(state === 'loading' || state === 'slow') && <Button type="button" variant="secondary" onClick={() => { abort.current?.abort(); setState('empty') }}>{t('qa.cancel')}</Button>}
            <Button type="submit" disabled={state === 'loading' || state === 'slow'}>{t('qa.ask')}</Button>
          </div>
        </div>
      </form>
      <div className="result" aria-live="polite">
        {state === 'empty' && (
          <div className="help-examples">
            <span className="help-examples-label">{t('try_examples')}</span>
            {examples.map((ex) => <button key={ex} type="button" className="help-example" dir="auto" onClick={() => setQ(ex)}>{ex}</button>)}
          </div>
        )}
        {(state === 'loading' || state === 'slow') && (<><p ref={summary} tabIndex={-1}>{t('qa.loading')} {state === 'slow' && t('qa.slow')}</p><Skeleton rows={2} /></>)}
        {state === 'error' && (<Message kind="error"><p ref={summary} tabIndex={-1}>{t('qa.error')}</p><div className="actions"><Button onClick={() => ask()}>{t('qa.try_again')}</Button><a className="btn btn-secondary" href="#ask-human">{t('qa.send_specialist')}</a></div></Message>)}
        {state === 'done' && ans && (
          <div className="answer-card help-answer">
            <p ref={summary} tabIndex={-1} className="summary"><strong>{ans.decision === 'answer_as_information' ? t('qa.answered') : t('qa.not_answered')}</strong></p>
            <p className="help-answer-chips"><Chip tone="draft" icon="✎">{t('qa.chip')}</Chip><Chip tone="info" icon="i">{ans.decision === 'legal_neutral' ? t('qa.legal_label') : t('qa.label')}</Chip></p>
            {ans.decision === 'answer_as_information' && (
              <>
                <p dir="auto" lang={lang}>{ans.body[lang]}</p>
                {lang !== 'ar' && <p className="hint">{t('qa.original')}</p>}
                <p className="hint">{t('qa.disclaimer')} {t('qa.value_status')}</p>
                <h3 className="help-sources-title">{t('qa.sources')}</h3>
                <div className="help-citations">{ans.citations.map((c) => <CitationBlock key={c.passage_id} c={c} lang={lang} />)}</div>
                <p>{t('qa.helpful')} <a className="btn btn-link" href="#ask-human">{t('qa.ask_human')}</a></p>
              </>
            )}
            {ans.decision === 'legal_neutral' && (
              <>
                <p>{t('qa.legal')} {t('qa.legal_own_choice')}</p>
                <div className="actions"><Button onClick={sendLegal}>{t('qa.send_licensed')}</Button></div>
              </>
            )}
            {(ans.decision === 'refuse_and_route' || ans.decision === 'out_of_corpus_refuse') && (
              <>
                <p>{ans.case_id ? t('qa.refusal') : t('qa.refusal_minimal')}</p>
                {ans.general_rule && (
                  <div>
                    <h3>{t('qa.general_rule')}</h3>
                    <p dir="auto">{ans.general_rule.body[lang]}</p>
                    <p className="hint">{t('qa.disclaimer')}</p>
                    {ans.general_rule.citations.map((c) => <CitationBlock key={c.passage_id} c={c} lang={lang} />)}
                  </div>
                )}
                {ans.case_id ? (
                  <p>{t('qa.case_created', { id: '' })} <Ident>{ans.case_id}</Ident> · <a className="btn btn-link" href="#cases">{t('qa.open_case')}</a> {t('qa.told')}</p>
                ) : (
                  <Message kind="warning">
                    <p>{ans.escalation_status === 'pending_escalation' ? t('qa.retrying') : t('qa.failed')}</p>
                    <div className="actions"><Button onClick={retry}>{t('qa.retry_now')}</Button><Button variant="secondary">{t('qa.contact')}</Button></div>
                  </Message>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
