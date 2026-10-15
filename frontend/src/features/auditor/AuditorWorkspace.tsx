import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Dialog, Empty, Field, Ident, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatAED, formatDate, formatDateTime } from '../../lib/format'
import FirewallCard, { type FirewallRow } from '../settings/FirewallCard'
import type { Bi, FlagDetail, WorkingFile } from '../audit/types'

interface QueueRow { id: string; company_id: string; company: Bi | null; status: string; review_deadline: string | null; open_exceptions: number; completeness_state: string | null; file_status: string | null; is_demo: boolean }
interface RegisterCheck { outcome: string; snapshot_id: string | null; checked_at: string; text: Bi }
interface EngagementDetail {
  id: string; company_id: string; company: Bi | null; status: string; auditor_name: string; register_ref: string | null; firm_name: string | null; engagement_manager: string; review_deadline: string | null
  working_file: WorkingFile | null; open_exceptions: number; register_check: RegisterCheck | null; firewall: FirewallRow | null; independence_declared: boolean
  evidence_mode: 'evidence_access' | 'supplied_documents_only'; badge: Bi; ai_notice: Bi; signing_enabled: boolean; primary_action: string; sign_off_label: Bi
  review_recorded: Bi | null; signed_outside: { text: Bi } | null; exceptions: (FlagDetail & { evidence_note?: Bi })[]; rejection_codes: string[]; is_demo: boolean
}

const pick = (b: Bi | null | undefined, lang: string) => (b ? (lang === 'ar' ? b.ar : b.en) : '')

/** SC13: queue of assigned engagements only; dense exception table; 'Record review' (signing stays OFF). */
export default function AuditorWorkspace() {
  const { t, i18n } = useTranslation('auditor')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const [rows, setRows] = useState<QueueRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<string | null>(null)
  const load = useCallback(() => get<{ engagements: QueueRow[] }>('/api/auditor/engagements').then((d) => setRows(d.engagements)).catch((e: ApiError) => setErr(e.code)), [])
  useEffect(() => { load() }, [load])
  if (sel) return <EngagementView id={sel} lang={lang} onBack={() => { setSel(null); load() }} />
  return (
    <div>
      <h1>{t('title')}</h1>
      {err && <Message kind="error">{t('error_generic')}</Message>}
      {!rows && !err && <><p aria-live="polite">{t('loading_list')}</p><Skeleton rows={3} /></>}
      {rows && rows.length === 0 && <Empty title={t('empty')} />}
      {rows && rows.length > 0 && (
        <Table headers={[t('queue.company'), t('queue.status'), t('queue.completeness'), t('queue.open'), t('queue.deadline')]}>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><button type="button" className="btn btn-link" onClick={() => setSel(r.id)}><bdi>{pick(r.company, lang)}</bdi></button>{r.is_demo && <> <Chip tone="neutral">{t('demo')}</Chip></>}</td>
              <td><Chip tone={r.status === 'review_recorded' ? 'neutral' : 'info'} icon={r.status === 'review_recorded' ? '◆' : undefined}>{t(`status.${r.status}`)}</Chip></td>
              <td>{r.completeness_state ? t(`completeness.${r.completeness_state}`) : '—'}</td>
              <td><Ident>{r.open_exceptions}</Ident></td>
              <td>{formatDate(r.review_deadline, lang)}</td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  )
}

function EngagementView({ id, lang, onBack }: { id: string; lang: string; onBack: () => void }) {
  const { t } = useTranslation('auditor')
  const [d, setD] = useState<EngagementDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<'papers' | 'exceptions' | 'register' | 'independence'>('exceptions')
  const [msg, setMsg] = useState<{ kind: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [reauthFor, setReauthFor] = useState<null | { action: string; body?: Record<string, unknown> }>(null)
  const [returnOpen, setReturnOpen] = useState<null | 'request_changes' | 'reject'>(null)
  const load = useCallback(() => get<EngagementDetail>(`/api/auditor/engagements/${id}`).then((x) => { setD(x); setErr(null) }).catch((e: ApiError) => setErr(e.code)), [id])
  useEffect(() => { load() }, [load])
  if (err === 'NOT_ASSIGNED') return <div><Message kind="error">{t('not_assigned')}</Message><Button variant="secondary" onClick={onBack}>{t('back')}</Button></div>
  if (err && !d) return <div><Message kind="error">{t('error')}</Message><Button onClick={load}>{t('register.retry')}</Button></div>
  if (!d) return <div><p aria-live="polite">{t('loading')}</p><Skeleton rows={6} /></div>
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
  return (
    <div>
      <Button variant="secondary" onClick={onBack}>{t('back')}</Button>
      <h1><bdi>{pick(d.company, lang)}</bdi></h1>
      <p><Chip tone="draft" icon="✎">{pick(d.badge, lang)}</Chip> <Chip tone="info">{t(`status.${d.status}`)}</Chip> {d.is_demo && <Chip tone="neutral">{t('demo')}</Chip>}</p>
      <p className="helper">{pick(d.ai_notice, lang)}</p>
      {d.evidence_mode === 'supplied_documents_only' && <Message kind="info">{t('supplied_only')}</Message>}
      {f?.signature_void && <Message kind="warning">{t('void')}</Message>}
      {d.review_recorded && <Message kind="info">{pick(d.review_recorded, lang)}</Message>}
      {d.signed_outside && <Message kind="info">{pick(d.signed_outside.text, lang)} <Chip tone="neutral">{t('outside.badge')}</Chip></Message>}
      <div className="tabs" role="tablist">
        {(['papers', 'exceptions', 'register', 'independence'] as const).map((k) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{t(`tabs.${k}`)}{k === 'exceptions' && d.open_exceptions > 0 ? ` (${d.open_exceptions})` : ''}</button>)}
      </div>
      {tab === 'papers' && f && (
        <Panel title={pick(f.header, lang)}>
          <p className="watermark"><span lang="en" dir="ltr">{f.watermark.en}</span> / <span lang="ar" dir="rtl">{f.watermark.ar}</span></p>
          <dl className="kv">{(f.ai_prepared_content.figures ?? []).map((x) => <div key={x.key} style={{ display: 'contents' }}><dt>{pick(x.label, lang)}</dt><dd>{x.value_fils != null ? <bdi dir="ltr">{formatAED(x.value_fils, lang)}</bdi> : `Gap ${x.gap ?? '?'}`}</dd></div>)}</dl>
          <a className="btn btn-secondary" href={`/api/auditor/engagements/${id}/export?lang=${lang}`} target="_blank" rel="noreferrer">{t('print')}</a>
        </Panel>
      )}
      {tab === 'exceptions' && <ExceptionTable d={d} lang={lang} onChanged={load} />}
      {tab === 'register' && (
        <Panel title={t('tabs.register')}>
          {d.register_check ? <p><Chip tone={registerOk ? 'neutral' : 'critical'}>{pick(d.register_check.text, lang)}</Chip></p> : <p>{t('register.not_checked')}</p>}
          {d.register_check && !registerOk && <Message kind="error">{d.register_check.outcome === 'blocked_unlisted' ? t('register.not_found') : t('register.unreachable')}</Message>}
          <Button variant="secondary" onClick={() => post(`/api/auditor/engagements/${id}/register-check`).then(load).catch(() => setMsg({ kind: 'error', text: t('register.unreachable') }))}>{t('register.retry')}</Button>
        </Panel>
      )}
      {tab === 'independence' && (
        <div>
          {d.firewall && <FirewallCard record={d.firewall} />}
          {d.independence_declared ? <Chip tone="neutral">{t('independence.declared')}</Chip> : <><Message kind="warning">{t('independence.required')}</Message><Button onClick={() => post(`/api/auditor/engagements/${id}/independence`).then(load)}>{t('independence.declare')}</Button></>}
          <SignedOutsideForm id={id} onSaved={load} />
        </div>
      )}
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <div className="card" style={{ position: 'sticky', bottom: 0, display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
        {f?.status === 'draft' && f.completeness_state !== 'incomplete' && <Button variant="secondary" onClick={() => act('start_review')}>{t('actions.start')}</Button>}
        <Button disabled={!registerOk || d.open_exceptions > 0 || f?.status !== 'under_review'} aria-describedby="record-help" onClick={() => setReauthFor({ action: 'record_review' })}>{t('actions.record')}</Button>
        <Button variant="secondary" disabled={f?.status !== 'under_review'} onClick={() => setReturnOpen('request_changes')}>{t('actions.return')}</Button>
        <Button variant="danger" disabled={f?.status !== 'under_review'} onClick={() => setReturnOpen('reject')}>{t('actions.reject')}</Button>
        <span id="record-help" className="muted">{d.open_exceptions > 0 ? t('actions.resolve_first', { n: d.open_exceptions }) : !registerOk ? t('register.not_checked') : ''}</span>
        <span className="muted">{pick(d.sign_off_label, lang)}</span>
      </div>
      <Dialog open={!!reauthFor} title={t('reauth.title')} onClose={() => setReauthFor(null)} labelledBy="reauth-title">
        <p>{t('reauth.body')}</p>
        {f && <p className="muted">{t('reauth.version', { v: f.version_no, hash: '' })}</p>}
        <Button onClick={() => reauthFor && act(reauthFor.action, reauthFor.body)}>{t('reauth.button')}</Button> <Button variant="secondary" onClick={() => setReauthFor(null)}>{t('actions.cancel')}</Button>
      </Dialog>
      {returnOpen && <ReturnForm kind={returnOpen} codes={d.rejection_codes} onCancel={() => setReturnOpen(null)} onSubmit={(body) => act(returnOpen, body)} />}
    </div>
  )
}

function ExceptionTable({ d, lang, onChanged }: { d: EngagementDetail; lang: string; onChanged: () => void }) {
  const { t } = useTranslation('auditor')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [confirmDismiss, setConfirmDismiss] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const decide = (flagId: string, decision: string) => post(`/api/auditor/engagements/${d.id}/exceptions/${flagId}/decide`, { decision, reason: notes[flagId] ?? '' }).then(() => { setConfirmDismiss(null); onChanged() }).catch((e: ApiError) => setErr(e.message))
  if (d.exceptions.length === 0) return <Empty title={t('exceptions.none')} />
  return (
    <Panel title={t('exceptions.open_n', { n: d.open_exceptions })}>
      {err && <Message kind="error">{err}</Message>}
      <Table headers={[t('exceptions.cols.rule'), t('exceptions.cols.severity'), t('exceptions.cols.status'), t('exceptions.cols.evidence'), t('exceptions.cols.basis'), t('exceptions.cols.decide')]}>
        {d.exceptions.map((x) => (
          <tr key={x.id}>
            <td>{pick(x.rule_title, lang)}<br /><Ident>{x.rule_id} {x.rule_version}</Ident><br /><Chip tone="draft" icon="✎">{pick(x.ai_label, lang)}</Chip></td>
            <td>{x.severity}</td>
            <td><Chip tone={x.status === 'New' ? 'attention' : 'neutral'}>{t(`exceptions.status.${x.status}`)}</Chip></td>
            <td>{x.evidence.map((r) => <div key={r.record_id}>{r.masked ? <span>🔒 {t('exceptions.masked')}</span> : <><Ident>{r.record_id}</Ident> · {formatDate(r.date, lang)} · <bdi dir="ltr">{formatAED(r.amount_fils ?? null, lang)}</bdi> · <bdi>{r.counterparty}</bdi></>}</div>)}{x.evidence_note && <p className="muted">{pick(x.evidence_note, lang)}</p>}</td>
            <td><code dir="ltr">{x.basis ? JSON.stringify(x.basis) : '—'}</code></td>
            <td>
              {x.status === 'New' ? (
                <>
                  <Field label={t('exceptions.note')} id={`note-${x.id}`}><textarea id={`note-${x.id}`} value={notes[x.id] ?? ''} onChange={(e) => setNotes({ ...notes, [x.id]: e.target.value })} /></Field>
                  <Button variant="secondary" disabled={(notes[x.id] ?? '').trim().length < 10} onClick={() => decide(x.id, 'confirm')}>{t('exceptions.confirm')}</Button>{' '}
                  {confirmDismiss === x.id ? <><span>{t('exceptions.dismiss_ask')}</span> <Button variant="danger" onClick={() => decide(x.id, 'dismiss')}>{t('exceptions.dismiss')}</Button></> : <Button variant="secondary" disabled={(notes[x.id] ?? '').trim().length < 10} onClick={() => setConfirmDismiss(x.id)}>{t('exceptions.dismiss')}</Button>}
                </>
              ) : <span className="muted">{x.decisions[0] ? `${x.decisions[0].by} · ${formatDateTime(x.decisions[0].at, lang)}` : ''}</span>}
            </td>
          </tr>
        ))}
      </Table>
    </Panel>
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
        <label><input type="checkbox" checked={release} onChange={(e) => setRelease(e.target.checked)} /> {t('actions.release_text')}</label>
        <div><Button type="submit" disabled={!code || tooShort}>{t('actions.submit')}</Button> <Button type="button" variant="secondary" onClick={onCancel}>{t('actions.cancel')}</Button></div>
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
      <form onSubmit={(e) => { e.preventDefault(); post(`/api/auditor/engagements/${id}/signed-outside`, v).then(onSaved).catch((x: ApiError) => setErr(x.message)) }}>
        <Field label={t('outside.signer')} id="so-signer"><input id="so-signer" value={v.signer_name} onChange={(e) => setV({ ...v, signer_name: e.target.value })} /></Field>
        <Field label={t('outside.register')} id="so-reg"><input id="so-reg" dir="ltr" value={v.register_number} onChange={(e) => setV({ ...v, register_number: e.target.value })} /></Field>
        <Field label={t('outside.date')} id="so-date"><input id="so-date" type="date" value={v.date_signed} onChange={(e) => setV({ ...v, date_signed: e.target.value })} /></Field>
        <Field label={t('outside.ref')} id="so-ref"><input id="so-ref" dir="ltr" value={v.document_reference} onChange={(e) => setV({ ...v, document_reference: e.target.value })} /></Field>
        <label><input type="checkbox" checked={v.confirmed} onChange={(e) => setV({ ...v, confirmed: e.target.checked })} /> {t('outside.confirm')}</label>
        <div><Button type="submit" disabled={!ok}>{t('outside.save')}</Button> <Chip tone="neutral">{t('outside.badge')}</Chip></div>
        {err && <Message kind="error">{err}</Message>}
      </form>
    </Panel>
  )
}
