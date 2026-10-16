import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Disclosure, Empty, Field, Ident, Message, PageHeader, Panel, Skeleton, StatCard, Table, Tabs } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatAED, formatDate, formatDateTime } from '../../lib/format'
import FirewallCard, { type FirewallRow } from '../settings/FirewallCard'
import type { Bi, FlagDetail, WorkingFile } from '../audit/types'
import { DueChip, NextStep, SectionHead } from '../det/ui'

interface QueueRow { id: string; company_id: string; company: Bi | null; status: string; review_deadline: string | null; open_exceptions: number; completeness_state: string | null; file_status: string | null; is_demo: boolean }
interface RegisterCheck { outcome: string; snapshot_id: string | null; checked_at: string; text: Bi }
interface EngagementDetail {
  id: string; company_id: string; company: Bi | null; status: string; auditor_name: string; register_ref: string | null; firm_name: string | null; engagement_manager: string; review_deadline: string | null
  working_file: WorkingFile | null; open_exceptions: number; register_check: RegisterCheck | null; firewall: FirewallRow | null; independence_declared: boolean
  evidence_mode: 'evidence_access' | 'supplied_documents_only'; badge: Bi; ai_notice: Bi; signing_enabled: boolean; primary_action: string; sign_off_label: Bi
  review_recorded: Bi | null; signed_outside: { text: Bi } | null; exceptions: (FlagDetail & { evidence_note?: Bi })[]; rejection_codes: string[]; is_demo: boolean
}

const pick = (b: Bi | null | undefined, lang: string) => (b ? (lang === 'ar' ? b.ar : b.en) : '')

const NEEDS_ACTION = new Set(['awaiting_review', 'under_review', 'in_preparation'])

/** SC13: queue of assigned engagements only; exception checklist; 'Record review' (signing stays OFF). */
export default function AuditorWorkspace() {
  const { t, i18n } = useTranslation('auditor')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const [rows, setRows] = useState<QueueRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<string | null>(null)
  const load = useCallback(() => get<{ engagements: QueueRow[] }>('/api/auditor/engagements').then((d) => setRows(d.engagements)).catch((e: ApiError) => setErr(e.code)), [])
  useEffect(() => { load() }, [load])
  if (sel) return <EngagementView id={sel} lang={lang} onBack={() => { setSel(null); load() }} />
  const active = (rows ?? []).filter((r) => NEEDS_ACTION.has(r.status))
  const openExc = (rows ?? []).reduce((n, r) => n + r.open_exceptions, 0)
  const byDeadline = [...active].sort((x, y) => (x.review_deadline ?? '9999').localeCompare(y.review_deadline ?? '9999'))
  const next = byDeadline[0]
  return (
    <div className="page det-ws">
      <PageHeader eyebrow={t('eyebrow')} title={t('title')} subtitle={t('subtitle')} />
      {err && <Message kind="error">{t('error_generic')}</Message>}
      {!rows && !err && <><p aria-live="polite" className="visually-hidden">{t('loading_list')}</p><div className="stat-grid">{[0, 1, 2].map((i) => <div key={i} className="card"><Skeleton rows={2} /></div>)}</div><Skeleton rows={3} /></>}
      {rows && (
        <>
          <div className="stat-grid">
            <StatCard icon="briefcase" label={t('stats.assigned')} value={<bdi dir="ltr">{rows.length}</bdi>} />
            <StatCard icon="file-check" tone={active.length ? 'info' : undefined} label={t('stats.to_review')} value={<bdi dir="ltr">{active.length}</bdi>} hint={t('stats.to_review_hint')} />
            <StatCard icon="alert" tone={openExc ? 'attention' : 'ok'} label={t('queue.open')} value={<bdi dir="ltr">{openExc}</bdi>} hint={t('stats.open_hint')} />
            <StatCard icon="calendar" label={t('stats.next_deadline')} value={next?.review_deadline ? <span className="nowrap">{formatDate(next.review_deadline, lang)}</span> : '—'} status={next?.review_deadline ? <DueChip date={next.review_deadline} /> : undefined} />
          </div>
          {next ? (
            <NextStep action={<Button variant="secondary" className="det-rowbtn" onClick={() => setSel(next.id)}>{t('open_engagement')}</Button>}>
              {next.open_exceptions > 0
                ? t('next', { company: pick(next.company, lang), n: next.open_exceptions, date: formatDate(next.review_deadline, lang) })
                : t('next_no_exc', { company: pick(next.company, lang), date: formatDate(next.review_deadline, lang) })}
            </NextStep>
          ) : rows.length > 0 ? (
            <NextStep tone="calm" icon="check">{t('next_none')}</NextStep>
          ) : null}
        </>
      )}
      {rows && rows.length === 0 && <Empty icon="briefcase" title={t('empty')} body={t('empty_next')} />}
      {rows && rows.length > 0 && (
        <Panel title={t('queue.title')} className="det-panel-flush" actions={<span className="hint">{t('count_n', { n: rows.length })}</span>}>
          <div className="table-compact det-table">
          <Table headers={[t('queue.company'), t('queue.status'), t('queue.completeness'), t('queue.open'), t('queue.deadline'), <span key="a" className="visually-hidden">{t('queue.action')}</span>]}>
            {rows.map((r) => (
              <tr key={r.id}>
                <td><button type="button" className="btn btn-link det-ref-btn" onClick={() => setSel(r.id)}><bdi>{pick(r.company, lang)}</bdi></button>{r.is_demo && <span className="det-cell-sub"><Chip tone="neutral">{t('demo')}</Chip></span>}</td>
                <td><Chip tone={r.status === 'review_recorded' ? 'ok' : r.status === 'rejected' ? 'critical' : 'info'} icon={r.status === 'review_recorded' ? '◆' : undefined}>{t(`status.${r.status}`)}</Chip></td>
                <td className="nowrap">{r.completeness_state ? t(`completeness.${r.completeness_state}`) : '—'}</td>
                <td className="num">{r.open_exceptions > 0 ? <Chip tone="attention" icon="!"><bdi dir="ltr">{r.open_exceptions}</bdi></Chip> : <bdi dir="ltr">0</bdi>}</td>
                <td className="date-cell">{formatDate(r.review_deadline, lang)}{NEEDS_ACTION.has(r.status) && <span className="det-cell-sub"><DueChip date={r.review_deadline} /></span>}</td>
                <td className="nowrap"><Button variant="secondary" className="det-rowbtn" onClick={() => setSel(r.id)}>{t('open_engagement')}</Button></td>
              </tr>
            ))}
          </Table>
          </div>
        </Panel>
      )}
    </div>
  )
}

type ViewTab = 'papers' | 'exceptions' | 'register' | 'independence'

function EngagementView({ id, lang, onBack }: { id: string; lang: string; onBack: () => void }) {
  const { t } = useTranslation('auditor')
  const [d, setD] = useState<EngagementDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<ViewTab>('exceptions')
  const [msg, setMsg] = useState<{ kind: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [reauthFor, setReauthFor] = useState<null | { action: string; body?: Record<string, unknown> }>(null)
  const [returnOpen, setReturnOpen] = useState<null | 'request_changes' | 'reject'>(null)
  const load = useCallback(() => get<EngagementDetail>(`/api/auditor/engagements/${id}`).then((x) => { setD(x); setErr(null) }).catch((e: ApiError) => setErr(e.code)), [id])
  useEffect(() => { load() }, [load])
  const back = <div className="det-back"><Button variant="link" className="btn-ghost" onClick={onBack}><Icon name="chevron-start" size={18} className="flip-rtl" />{t('back')}</Button></div>
  if (err === 'NOT_ASSIGNED') return <div className="page det-ws">{back}<Message kind="error">{t('not_assigned')}</Message></div>
  if (err && !d) return <div className="page det-ws">{back}<Message kind="error">{t('error')}</Message><Button onClick={load}>{t('register.retry')}</Button></div>
  if (!d) return <div className="page det-ws">{back}<p aria-live="polite" className="visually-hidden">{t('loading')}</p><Skeleton rows={6} /></div>
  const f = d.working_file
  const registerOk = d.register_check?.outcome === 'allowed'
  const act = async (action: string, body: Record<string, unknown> = {}) => {
    try {
      let reauth_ref: string | undefined
      if (action !== 'start_review') reauth_ref = (await post<{ reauth_ref: string }>('/api/auditor/reauth')).reauth_ref
      await post(`/api/auditor/engagements/${id}/review`, { action, reauth_ref, ...body })
      setMsg({ kind: 'success', text: action === 'record_review' ? t('recorded') : t(`status.${action === 'start_review' ? 'under_review' : action === 'reject' ? 'rejected' : 'returned_to_preparation'}`) })
      setReauthFor(null); setReturnOpen(null)
      load()
    } catch (e) {
      const code = (e as ApiError).code
      setMsg({ kind: 'error', text: code === 'EXCEPTIONS_OPEN' ? t('actions.resolve_first', { n: d.open_exceptions }) : code === 'REAUTH_REQUIRED' ? t('reauth.failed') : code.startsWith('BLOCKED_') ? t('register.not_checked') : (e as Error).message || t('error_generic') })
    }
  }
  const tabs: { id: ViewTab; label: string; badge?: number }[] = [
    { id: 'papers', label: t('tabs.papers') },
    { id: 'exceptions', label: t('tabs.exceptions'), badge: d.open_exceptions > 0 ? d.open_exceptions : undefined },
    { id: 'register', label: t('tabs.register') },
    { id: 'independence', label: t('tabs.independence') },
  ]
  const help = d.open_exceptions > 0 ? t('actions.resolve_first', { n: d.open_exceptions }) : !registerOk ? t('register.not_checked') : f?.status === 'draft' ? t('actions.start_first') : ''
  return (
    <div className="page det-ws">
      {back}
      <PageHeader
        eyebrow={t('engagement')}
        title={<bdi>{pick(d.company, lang)}</bdi>}
        subtitle={pick(d.ai_notice, lang)}
        meta={<><Chip tone="draft" icon="✎">{pick(d.badge, lang)}</Chip><Chip tone="info">{t(`status.${d.status}`)}</Chip>{d.is_demo && <Chip tone="neutral">{t('demo')}</Chip>}</>}
      />
      {d.evidence_mode === 'supplied_documents_only' && <Message kind="info">{t('supplied_only')}</Message>}
      {f?.signature_void && <Message kind="warning">{t('void')}</Message>}
      {d.review_recorded && <Message kind="info">{pick(d.review_recorded, lang)}</Message>}
      {d.signed_outside && <Message kind="info">{pick(d.signed_outside.text, lang)} <Chip tone="neutral">{t('outside.badge')}</Chip></Message>}
      <dl className="det-facts">
        <div><dt>{t('queue.completeness')}</dt><dd>{f?.completeness_state ? t(`completeness.${f.completeness_state}`) : '—'}</dd></div>
        <div><dt>{t('queue.open')}</dt><dd><bdi dir="ltr">{d.open_exceptions}</bdi></dd></div>
        <div><dt>{t('queue.deadline')}</dt><dd className="nowrap">{formatDate(d.review_deadline, lang)}</dd></div>
        <div><dt>{t('tabs.register')}</dt><dd>{d.register_check ? <Chip tone={registerOk ? 'ok' : 'critical'} icon={registerOk ? '✓' : '!'}>{registerOk ? t('register.ok_short') : t('register.blocked_short')}</Chip> : '—'}</dd></div>
        {f && <div><dt>{t('version')}</dt><dd><bdi dir="ltr">v{f.version_no}</bdi></dd></div>}
      </dl>
      <Tabs label={t('tabs.label')} idPrefix="aud" value={tab} onChange={setTab} tabs={tabs} />
      <div role="tabpanel" id={`aud-${tab}-panel`} aria-labelledby={`aud-${tab}`}>
        {tab === 'papers' && f && (
          <Panel title={pick(f.header, lang)} actions={<a className="btn btn-secondary det-rowbtn" href={`/api/auditor/engagements/${id}/export?lang=${lang}`} target="_blank" rel="noreferrer"><Icon name="external" size={16} />{t('print')}</a>}>
            <p className="watermark"><span lang="en" dir="ltr">{f.watermark.en}</span> / <span lang="ar" dir="rtl">{f.watermark.ar}</span></p>
            <dl className="det-kpi-kv" style={{ marginTop: 16, maxWidth: 640 }}>{(f.ai_prepared_content.figures ?? []).map((x) => <div key={x.key} style={{ display: 'contents' }}><dt>{pick(x.label, lang)}</dt><dd>{x.value_fils != null ? <bdi dir="ltr">{formatAED(x.value_fils, lang)}</bdi> : `Gap ${x.gap ?? '?'}`}</dd></div>)}</dl>
          </Panel>
        )}
        {tab === 'exceptions' && <ExceptionList d={d} lang={lang} onChanged={load} />}
        {tab === 'register' && (
          <Panel title={t('tabs.register')} actions={<Button variant="secondary" className="det-rowbtn" onClick={() => post(`/api/auditor/engagements/${id}/register-check`).then(load).catch(() => setMsg({ kind: 'error', text: t('register.unreachable') }))}>{t('register.retry')}</Button>}>
            {d.register_check ? (
              <div className="det-status-card" style={{ padding: 0 }}>
                <p><Chip tone={registerOk ? 'ok' : 'critical'} icon={registerOk ? '✓' : '!'}>{pick(d.register_check.text, lang)}</Chip></p>
                <p className="hint">{t('register.checked_at', { when: formatDateTime(d.register_check.checked_at, lang) })}{d.register_check.snapshot_id && <> · <bdi dir="ltr">{d.register_check.snapshot_id}</bdi></>}</p>
              </div>
            ) : <p>{t('register.not_checked')}</p>}
            {d.register_check && !registerOk && <Message kind="error">{d.register_check.outcome === 'blocked_unlisted' ? t('register.not_found') : t('register.unreachable')}</Message>}
          </Panel>
        )}
        {tab === 'independence' && (
          <div className="det-stack">
            {d.firewall && <FirewallCard record={d.firewall} />}
            <Panel title={t('independence.title')}>
              {d.independence_declared ? <Chip tone="ok" icon="✓">{t('independence.declared')}</Chip> : <><Message kind="warning">{t('independence.required')}</Message><Button onClick={() => post(`/api/auditor/engagements/${id}/independence`).then(load)}>{t('independence.declare')}</Button></>}
            </Panel>
            <SignedOutsideForm id={id} onSaved={load} />
          </div>
        )}
      </div>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <div className="det-actionbar" role="region" aria-label={t('actions.bar')}>
        <div className="det-actionbar-help">
          <strong>{t(`status.${d.status}`)}</strong>
          {help && <span id="record-help">{help}</span>}
          <span>{pick(d.sign_off_label, lang)}</span>
        </div>
        <div className="det-actionbar-buttons">
          {f?.status === 'draft' && f.completeness_state !== 'incomplete' && <Button onClick={() => act('start_review')}>{t('actions.start')}</Button>}
          <Button disabled={!registerOk || d.open_exceptions > 0 || f?.status !== 'under_review'} aria-describedby={help ? 'record-help' : undefined} onClick={() => setReauthFor({ action: 'record_review' })}>{t('actions.record')}</Button>
          <Button variant="secondary" disabled={f?.status !== 'under_review'} onClick={() => setReturnOpen('request_changes')}>{t('actions.return')}</Button>
          <Button variant="danger" disabled={f?.status !== 'under_review'} onClick={() => setReturnOpen('reject')}>{t('actions.reject')}</Button>
        </div>
      </div>
      <Dialog open={!!reauthFor} title={t('reauth.title')} onClose={() => setReauthFor(null)} labelledBy="reauth-title">
        <p>{t('reauth.body')}</p>
        {f && <p className="muted">{t('reauth.version', { v: f.version_no, hash: '' })}</p>}
        <div className="dialog-actions">
          <Button variant="secondary" onClick={() => setReauthFor(null)}>{t('actions.cancel')}</Button>
          <Button onClick={() => reauthFor && act(reauthFor.action, reauthFor.body)}>{t('reauth.button')}</Button>
        </div>
      </Dialog>
      {returnOpen && <ReturnForm kind={returnOpen} codes={d.rejection_codes} onCancel={() => setReturnOpen(null)} onSubmit={(body) => act(returnOpen, body)} />}
    </div>
  )
}

const basisValue = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v))

function ExceptionList({ d, lang, onChanged }: { d: EngagementDetail; lang: string; onChanged: () => void }) {
  const { t } = useTranslation('auditor')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [confirmDismiss, setConfirmDismiss] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const decide = (flagId: string, decision: string) => post(`/api/auditor/engagements/${d.id}/exceptions/${flagId}/decide`, { decision, reason: notes[flagId] ?? '' }).then(() => { setConfirmDismiss(null); onChanged() }).catch((e: ApiError) => setErr(e.message))
  if (d.exceptions.length === 0) return <Empty icon="check" title={t('exceptions.none')} body={t('exceptions.none_next')} />
  return (
    <section aria-labelledby="exc-title">
      <SectionHead id="exc-title" first title={d.open_exceptions > 0 ? t('exceptions.open_n', { n: d.open_exceptions }) : t('exceptions.all_done')} hint={t('exceptions.how')} />
      {err && <Message kind="error">{err}</Message>}
      <ol className="det-exc-list">
        {d.exceptions.map((x, i) => {
          const open = x.status === 'New'
          const note = notes[x.id] ?? ''
          const len = note.trim().length
          const decision = x.decisions[0]
          return (
            <li key={x.id} className={`det-exc ${open ? 'is-open' : 'is-done'}`} aria-labelledby={`exc-${x.id}-title`}>
              <div className="det-exc-main">
                <div className="det-exc-head">
                  <span className="det-exc-step" aria-hidden="true">{open ? <bdi dir="ltr">{i + 1}</bdi> : '✓'}</span>
                  <div>
                    <h3 id={`exc-${x.id}-title`}>{pick(x.rule_title, lang)}</h3>
                    <div className="det-exc-sub">
                      <Ident>{x.rule_id} {x.rule_version}</Ident>
                      <Chip tone={x.severity === 'High' ? 'urgent' : x.severity === 'Medium' ? 'attention' : 'neutral'}>{t(`severity.${x.severity}`, { defaultValue: x.severity })}</Chip>
                      <Chip tone={open ? 'attention' : 'ok'}>{t(`exceptions.status.${x.status}`)}</Chip>
                      <Chip tone="draft" icon="✎">{pick(x.ai_label, lang)}</Chip>
                    </div>
                  </div>
                </div>
                <div>
                  <p className="det-exc-label">{t('exceptions.cols.evidence')}</p>
                  <ul className="det-evidence">
                    {x.evidence.map((r) => (
                      <li key={r.record_id}>
                        {r.masked ? <span>🔒 {t('exceptions.masked')}</span> : (
                          <>
                            <Ident>{r.record_id}</Ident>
                            <span className="nowrap">{formatDate(r.date, lang)}</span>
                            <bdi dir="ltr" className="amount">{formatAED(r.amount_fils ?? null, lang)}</bdi>
                            {r.counterparty && <bdi>{r.counterparty}</bdi>}
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                  {x.evidence_note && <p className="hint" style={{ marginTop: 6 }}>{pick(x.evidence_note, lang)}</p>}
                </div>
                {x.basis && (
                  <Disclosure summary={t('exceptions.cols.basis')}>
                    <dl className="det-basis">
                      {Object.entries(x.basis).map(([k, v]) => <div key={k} style={{ display: 'contents' }}><dt><bdi dir="ltr">{k}</bdi></dt><dd><bdi dir="ltr">{basisValue(v)}</bdi></dd></div>)}
                    </dl>
                  </Disclosure>
                )}
              </div>
              <div className="det-exc-decide">
                <p className="det-exc-label">{t('exceptions.cols.decide')}</p>
                {open ? (
                  <>
                    <Field label={t('exceptions.note')} id={`note-${x.id}`}>
                      <textarea id={`note-${x.id}`} value={note} aria-describedby={`note-${x.id}-count`} onChange={(e) => setNotes({ ...notes, [x.id]: e.target.value })} />
                    </Field>
                    <span id={`note-${x.id}-count`} className={`det-exc-count ${len >= 10 ? 'is-ok' : ''}`}>{len >= 10 ? t('exceptions.count_ok') : t('exceptions.count', { n: len })}</span>
                    {confirmDismiss === x.id ? (
                      <div className="det-exc-ask" role="alert">
                        <span>{t('exceptions.dismiss_ask')}</span>
                        <div className="det-exc-buttons">
                          <Button variant="danger" onClick={() => decide(x.id, 'dismiss')}>{t('exceptions.dismiss')}</Button>
                          <Button variant="secondary" onClick={() => setConfirmDismiss(null)}>{t('actions.cancel')}</Button>
                        </div>
                      </div>
                    ) : (
                      <div className="det-exc-buttons">
                        <Button variant="secondary" disabled={len < 10} onClick={() => decide(x.id, 'confirm')}>{t('exceptions.confirm')}</Button>
                        <Button variant="secondary" disabled={len < 10} onClick={() => setConfirmDismiss(x.id)}>{t('exceptions.dismiss')}</Button>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="hint">
                    <p><Chip tone="ok" icon="✓">{t(`exceptions.status.${x.status}`)}</Chip></p>
                    {decision && <p>{decision.by} · <span className="nowrap">{formatDateTime(decision.at, lang)}</span></p>}
                    {decision?.reason && <p>“{decision.reason}”</p>}
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function ReturnForm({ kind, codes, onCancel, onSubmit }: { kind: 'request_changes' | 'reject'; codes: string[]; onCancel: () => void; onSubmit: (body: Record<string, unknown>) => void }) {
  const { t, i18n } = useTranslation('auditor')
  const [code, setCode] = useState('')
  const [text, setText] = useState('')
  const [release, setRelease] = useState(false)
  const tooShort = text.trim().length > 0 && text.trim().length < 10
  return (
    <Dialog open title={kind === 'reject' ? t('actions.reject') : t('actions.return')} onClose={onCancel} labelledBy="return-title">
      <form onSubmit={(e) => { e.preventDefault(); onSubmit({ reason_code: code, free_text: text || undefined, release_free_text: release, reason_language: i18n.language.startsWith('ar') ? 'ar' : 'en' }) }}>
        <Field label={t('actions.reason_code')} id="ret-code" hint={t('actions.reason_help')}>
          <select id="ret-code" value={code} onChange={(e) => setCode(e.target.value)} required><option value="" />{codes.map((c) => <option key={c} value={c}>{t(`actions.codes.${c}`)}</option>)}</select>
        </Field>
        <Field label={t('actions.free_text')} id="ret-text"><textarea id="ret-text" value={text} onChange={(e) => setText(e.target.value)} aria-invalid={tooShort} /></Field>
        <label className="check"><input type="checkbox" checked={release} onChange={(e) => setRelease(e.target.checked)} /> {t('actions.release_text')}</label>
        <div className="dialog-actions"><Button type="button" variant="secondary" onClick={onCancel}>{t('actions.cancel')}</Button><Button type="submit" disabled={!code || tooShort}>{t('actions.submit')}</Button></div>
      </form>
    </Dialog>
  )
}

function SignedOutsideForm({ id, onSaved }: { id: string; onSaved: () => void }) {
  const { t } = useTranslation('auditor')
  const [v, setV] = useState({ signer_name: '', register_number: '', date_signed: '', document_reference: '', confirmed: false })
  const [err, setErr] = useState<string | null>(null)
  const ok = v.signer_name && v.register_number && v.date_signed && v.document_reference && v.confirmed
  return (
    <Panel title={t('outside.title')}>
      <p className="det-note"><Icon name="info" size={16} />{t('outside.hint')}</p>
      <form onSubmit={(e) => { e.preventDefault(); post(`/api/auditor/engagements/${id}/signed-outside`, v).then(onSaved).catch((x: ApiError) => setErr(x.message)) }}>
        <div className="det-form-grid">
        <Field label={t('outside.signer')} id="so-signer"><input id="so-signer" value={v.signer_name} onChange={(e) => setV({ ...v, signer_name: e.target.value })} /></Field>
        <Field label={t('outside.register')} id="so-reg"><input id="so-reg" dir="ltr" value={v.register_number} onChange={(e) => setV({ ...v, register_number: e.target.value })} /></Field>
        <Field label={t('outside.date')} id="so-date"><input id="so-date" type="date" value={v.date_signed} onChange={(e) => setV({ ...v, date_signed: e.target.value })} /></Field>
        <Field label={t('outside.ref')} id="so-ref"><input id="so-ref" dir="ltr" value={v.document_reference} onChange={(e) => setV({ ...v, document_reference: e.target.value })} /></Field>
        </div>
        <label className="check"><input type="checkbox" checked={v.confirmed} onChange={(e) => setV({ ...v, confirmed: e.target.checked })} /> {t('outside.confirm')}</label>
        <div className="actions"><Button type="submit" disabled={!ok}>{t('outside.save')}</Button> <Chip tone="neutral">{t('outside.badge')}</Chip></div>
        {err && <Message kind="error">{err}</Message>}
      </form>
    </Panel>
  )
}
