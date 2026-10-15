import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Empty, Field, Ident, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'

type Bi = { en: string; ar: string }
interface Meta { case_id: string; module: string; priority: string; status: string; escalation_reason: string; queue: string; specialist_type: string; assigned: boolean; assigned_role_label: string | null; flags: string[]; escalated_at: string; consent_decision: string | null; consent_requested_at: string | null; due_date: string | null; turnaround: { active_working_days: number; raw_working_days: number; paused_now: boolean }; is_demo: boolean }
interface Alert { id: string; type: string; case_id: string | null; created_at: string; recipients: string[]; escalated_to_pilot_manager: boolean }
interface Queue { mode: 'specialist' | 'ops'; specialist_type?: string; cases: Meta[]; unassigned?: Meta[]; alerts?: Alert[]; tax_path_enabled: boolean; lawyer_path_enabled: boolean }
interface Detail { mode: 'specialist' | 'ops'; case_id?: string; case_type?: string; escalation_reason?: string; deadline?: string | null; priority?: string; company_ref?: string; title?: string | null; status?: string; consent_decision?: string | null; locked_items?: { item: string; locked: boolean; cause: string }[]; metadata: Meta; access_log?: { who: string; role: string; what: string; when: string; result: string; reason: string | null }[]; consent_wait: { day: number; reminder_days: number[]; ops_alert_day: number; close_day: number; reopen_window: number; decision: string | null } | null; candidates?: { identity_uuid: string; status: string; valid_to: string | null; register: string; firm_agreement_signed: boolean }[] }

const SCOPE_ITEMS = ['return', 'tax profile', 'audit file', 'invoice', 'bank statement', 'ledger']

export default function CaseQueue() {
  const { t, i18n } = useTranslation('cases')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const [q, setQ] = useState<Queue | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<'mine' | 'unassigned' | 'alerts'>('mine')
  const [sel, setSel] = useState<string | null>(null)
  const load = useCallback(() => get<Queue>('/api/cases/queue').then(setQ).catch((e: ApiError) => setErr(e.code)), [])
  useEffect(() => { load() }, [load])
  const rows = tab === 'mine' ? q?.cases ?? [] : q?.unassigned ?? []
  return (
    <div>
      <h1>{t('title')}</h1>
      {q && <p className="hint">{t(`mode.${q.mode}`)} <Chip tone="draft" icon="✎">{t('ai_label')}</Chip></p>}
      {q && q.mode === 'specialist' && ((q.specialist_type === 'tax' && !q.tax_path_enabled) || (q.specialist_type === 'lawyer' && !q.lawyer_path_enabled)) && <Message kind="warning">{t('path_off')}</Message>}
      {err && <Message kind="error">{t('error')}</Message>}
      {sel ? <CaseDetail id={sel} lang={lang} onBack={() => { setSel(null); load() }} /> : (
        <>
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === 'mine'} onClick={() => setTab('mine')}>{t('tabs.mine')}</button>
            {q?.mode === 'specialist' && <button role="tab" aria-selected={tab === 'unassigned'} onClick={() => setTab('unassigned')}>{t('tabs.unassigned')}</button>}
            {q?.mode === 'ops' && <button role="tab" aria-selected={tab === 'alerts'} onClick={() => setTab('alerts')}>{t('tabs.alerts')}</button>}
          </div>
          {!q && !err && (<><p>{t('loading')}</p><Skeleton /></>)}
          {q && tab !== 'alerts' && (rows.length === 0 ? <Empty title={t(tab === 'mine' ? 'empty_mine' : 'empty_unassigned')} /> : (
            <Table headers={[t('cols.case'), t('cols.module'), t('cols.priority'), t('cols.status'), t('cols.reason'), t('cols.escalated'), t('cols.turnaround')]}>
              {rows.map((c) => (
                <tr key={c.case_id}>
                  <td><button type="button" className="btn btn-link" onClick={() => setSel(c.case_id)}><Ident>{c.case_id.slice(0, 13)}</Ident></button> {c.flags.map((f) => <Chip key={f} tone="attention" icon="!">{t(`flags.${f}`, { defaultValue: f })}</Chip>)}</td>
                  <td>{c.module}</td>
                  <td><Chip tone={c.priority === 'deadline_near' ? 'urgent' : 'neutral'}>{t(`priority.${c.priority}`)}</Chip></td>
                  <td><Chip tone={c.status === 'resolved' ? 'ok' : c.status === 'awaiting_consent' ? 'attention' : 'info'}>{t(`status.${c.status}`)}</Chip></td>
                  <td><Ident>{c.escalation_reason}</Ident></td>
                  <td>{formatDateTime(c.escalated_at, lang)}</td>
                  <td><Ident>{c.turnaround.active_working_days} / {c.turnaround.raw_working_days}</Ident>{c.turnaround.paused_now && ' ⏸'}</td>
                </tr>
              ))}
            </Table>
          ))}
          {q && tab === 'alerts' && ((q.alerts ?? []).length === 0 ? <Empty title={t('empty_alerts')} /> : (
            <Table headers={[t('alerts.type'), t('alerts.case'), t('alerts.created'), '']}>
              {(q.alerts ?? []).map((a) => (
                <tr key={a.id}>
                  <td><Ident>{a.type}</Ident> {a.escalated_to_pilot_manager && <Chip tone="urgent" icon="!">{t('alerts.escalated')}</Chip>}</td>
                  <td>{a.case_id ? <button type="button" className="btn btn-link" onClick={() => setSel(a.case_id!)}><Ident>{a.case_id.slice(0, 13)}</Ident></button> : '—'}</td>
                  <td>{formatDateTime(a.created_at, lang)}</td>
                  <td><Button variant="secondary" onClick={() => post(`/api/cases/alerts/${a.id}/acknowledge`).then(load)}>{t('actions.acknowledge')}</Button></td>
                </tr>
              ))}
            </Table>
          ))}
        </>
      )}
    </div>
  )
}

function CaseDetail({ id, lang, onBack }: { id: string; lang: string; onBack: () => void }) {
  const { t } = useTranslation('cases')
  const [d, setD] = useState<Detail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [label, setLabel] = useState<Bi | null>(null)
  const [scope, setScope] = useState<string[]>([])
  const [reqCode, setReqCode] = useState('')
  const [outcome, setOutcome] = useState('a')
  const [limitation, setLimitation] = useState(false)
  const [closeCode, setCloseCode] = useState('duplicate')
  const [key, setKey] = useState('')
  const [assignee, setAssignee] = useState('')
  const [itemState, setItemState] = useState<Record<string, string>>({})
  const load = useCallback(() => get<Detail>(`/api/cases/${id}`).then((x) => { setD(x); setErr(null) }).catch((e: ApiError) => setErr(e.code)), [id])
  useEffect(() => { load() }, [load])
  const act = async (path: string, body?: unknown) => {
    setErr(null)
    try {
      const r = await post<{ output_label?: Bi | null }>(`/api/cases/${id}/${path}`, body)
      if (r && r.output_label) setLabel(r.output_label)
      setMsg(path)
      load()
    } catch (e) {
      setErr((e as ApiError).code)
    }
  }
  const openItem = async (item: string) => {
    setItemState((s) => ({ ...s, [item]: 'checking' }))
    try {
      await get(`/api/cases/${id}/items/${encodeURIComponent(item)}`)
      setItemState((s) => ({ ...s, [item]: 'opened' }))
    } catch (e) {
      setItemState((s) => ({ ...s, [item]: (e as ApiError).code }))
    }
    load()
  }
  if (!d && !err) return <Skeleton />
  if (!d) return <Message kind="error">{err === 'NOT_ASSIGNED' ? 'You no longer have access to this case.' : t('error')} <Button variant="link" onClick={onBack}>←</Button></Message>
  const m = d.metadata
  const closed = ['rejected', 'resolved', 'closed', 'closed_no_consent'].includes(m.status)
  const cw = d.consent_wait
  return (
    <Panel title={<><Ident>{id}</Ident> · {m.module} · <Chip tone={m.priority === 'deadline_near' ? 'urgent' : 'neutral'}>{t(`priority.${m.priority}`)}</Chip> <Chip tone="info">{t(`status.${m.status}`)}</Chip></>} id="case" actions={<Button variant="secondary" onClick={onBack}>←</Button>}>
      {err && <Message kind="error"><Ident>{err}</Ident>{err.startsWith('ENTITLEMENT') || err.endsWith('SWITCHED_OFF') ? ` · ${t('path_off')}` : ''}</Message>}
      {msg && <Message kind="success"><Ident>{msg}</Ident></Message>}
      {label && <Message kind="info"><strong>{t('output_label')}:</strong> {label[lang as 'en' | 'ar']} <Chip tone="draft" icon="✎">{t('ai_label')}</Chip></Message>}
      {d.mode === 'specialist' && (
        <section aria-labelledby="summary-h">
          <h3 id="summary-h">{t('summary.title')}</h3>
          <p className="hint">{t('summary.hint')}</p>
          <dl className="grid">
            <div><dt>{t('summary.reference')}</dt><dd><Ident>{d.case_id}</Ident></dd></div>
            <div><dt>{t('summary.type')}</dt><dd>{d.case_type}</dd></div>
            <div><dt>{t('summary.reason')}</dt><dd><Ident>{d.escalation_reason}</Ident></dd></div>
            <div><dt>{t('summary.deadline')}</dt><dd>{d.deadline ? formatDate(d.deadline, lang) : '—'}</dd></div>
            <div><dt>{t('summary.priority')}</dt><dd>{t(`priority.${d.priority}`)}</dd></div>
            <div><dt>{t('summary.company')}</dt><dd><Ident>{d.company_ref}</Ident></dd></div>
            <div><dt>{t('summary.owner_title')}</dt><dd>{d.title ?? '—'}</dd></div>
          </dl>
          {(d.locked_items ?? []).length > 0 && (
            <ul>
              {(d.locked_items ?? []).map((it) => (
                <li key={it.item}>
                  <Chip tone={d.consent_decision === 'granted' ? 'ok' : 'neutral'} icon={d.consent_decision === 'granted' ? '✓' : '🔒'}>{t(`scope_items.${it.item}`, { defaultValue: it.item })}{d.consent_decision !== 'granted' ? ` · ${t('summary.locked')}` : ''}</Chip>{' '}
                  <Button variant="link" aria-disabled={d.consent_decision !== 'granted'} onClick={() => openItem(it.item)}>{t('summary.open_item')}</Button>
                  {itemState[it.item] === 'checking' && <span aria-live="polite"> {t('summary.checking')}</span>}
                  {itemState[it.item] === 'opened' && <span> {t('summary.opened')}</span>}
                  {itemState[it.item] && itemState[it.item] !== 'checking' && itemState[it.item] !== 'opened' && <Message kind="error">{t('summary.no_access')} <Ident>{itemState[it.item]}</Ident></Message>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {cw && (
        <section aria-labelledby="cw-h">
          <h3 id="cw-h">{t('consent_wait.title')}</h3>
          <p>{t('consent_wait.day', { day: cw.day })} · {t('consent_wait.decision')}: {cw.decision ?? '—'}</p>
          <ol>
            {cw.reminder_days.map((dd) => <li key={dd}>{t('consent_wait.reminder', { day: dd })}{cw.day >= dd ? ' ✓' : ''}</li>)}
            <li>{t('consent_wait.ops', { day: cw.ops_alert_day })}{cw.day >= cw.ops_alert_day ? ' ✓' : ''}</li>
            <li>{t('consent_wait.close', { day: cw.close_day })}{m.status === 'closed_no_consent' ? ' ✓' : ''}</li>
            <li>{t('consent_wait.reopen', { days: cw.reopen_window })}</li>
          </ol>
          {d.mode === 'ops' && <Button variant="secondary" onClick={() => act('consent-wait/run')}>{t('consent_wait.run')}</Button>}
        </section>
      )}
      {d.mode === 'ops' && !closed && (
        <form onSubmit={(e) => { e.preventDefault(); act('assign', { assignee_uuid: assignee }) }}>
          <Field label={t('actions.assignee')} id="assignee">
            <select id="assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value="">—</option>
              {(d.candidates ?? []).map((c) => <option key={c.identity_uuid} value={c.identity_uuid}>{c.identity_uuid} · {c.register} · {c.status}{c.valid_to ? ` · ${formatDate(c.valid_to, lang)}` : ''}</option>)}
            </select>
          </Field>
          <Button type="submit" disabled={!assignee}>{m.assigned ? t('actions.reassign') : t('actions.assign')}</Button>
        </form>
      )}
      {d.mode === 'specialist' && !closed && (
        <div className="actions-block">
          <fieldset>
            <legend>{t('actions.accept_scope')}</legend>
            {SCOPE_ITEMS.map((s) => <label key={s} className="checkbox"><input type="checkbox" checked={scope.includes(s)} onChange={(e) => setScope((x) => (e.target.checked ? [...x, s] : x.filter((y) => y !== s)))} /> {t(`scope_items.${s}`)}</label>)}
            <div className="actions"><Button onClick={() => act('accept', { requested_scope: scope.map((s) => ({ module: m.module, data_class: s })), purpose: 'case review' })}>{t('actions.accept')}</Button></div>
          </fieldset>
          <div className="actions"><Button variant="secondary" onClick={() => act('first-response', {})}>{t('actions.first_response')}</Button></div>
          <form onSubmit={(e) => { e.preventDefault(); act('request-info', { request_code: reqCode }) }}>
            <Field label={t('actions.request_code')} id="req-code"><input id="req-code" value={reqCode} onChange={(e) => setReqCode(e.target.value)} maxLength={40} dir="ltr" /></Field>
            <Button type="submit" variant="secondary" disabled={!reqCode}>{t('actions.request_info')}</Button>
          </form>
          <form onSubmit={(e) => { e.preventDefault(); act('resolve', { outcome, limitation }) }}>
            <Field label={t('actions.outcome')} id="outcome">
              <select id="outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>{['a', 'b', 'c'].map((o) => <option key={o} value={o}>{t(`actions.outcomes.${o}`)}</option>)}</select>
            </Field>
            <label className="checkbox"><input type="checkbox" checked={limitation} onChange={(e) => setLimitation(e.target.checked)} /> {t('actions.limitation')}</label>
            <div className="actions"><Button type="submit">{t('actions.resolve')}</Button></div>
          </form>
          {m.flags.includes('manual_review_key_incomplete') && (
            <form onSubmit={(e) => { e.preventDefault(); act('complete-key', { matter_key: key }) }}>
              <Field label={t('actions.complete_key')} id="mk"><input id="mk" value={key} onChange={(e) => setKey(e.target.value)} dir="ltr" /></Field>
              <Button type="submit" variant="secondary" disabled={!key}>{t('actions.complete_key')}</Button>
            </form>
          )}
        </div>
      )}
      {!closed && (
        <form onSubmit={(e) => { e.preventDefault(); act('close', { reason_code: closeCode }) }}>
          <Field label={t('actions.close')} id="close-code">
            <select id="close-code" value={closeCode} onChange={(e) => setCloseCode(e.target.value)}>{['key_incomplete_closed', 'duplicate', 'not_in_scope', 'withdrawn_by_ops'].map((c) => <option key={c} value={c}>{t(`actions.close_codes.${c}`)}</option>)}</select>
          </Field>
          <Button type="submit" variant="danger">{t('actions.close')}</Button>
        </form>
      )}
      {d.access_log && (
        <section aria-labelledby="log-h">
          <h3 id="log-h">{t('access_log.title')}</h3>
          {d.access_log.length === 0 ? <p>{t('access_log.empty')}</p> : (
            <Table headers={[t('access_log.who'), t('access_log.what'), t('access_log.when'), t('access_log.result')]}>
              {d.access_log.map((r, i) => <tr key={i}><td><Ident>{r.who}</Ident></td><td>{r.what}</td><td>{formatDateTime(r.when, lang)}</td><td><Chip tone={r.result === 'Allowed' ? 'ok' : 'critical'}>{r.result}{r.reason ? ` · ${r.reason}` : ''}</Chip></td></tr>)}
            </Table>
          )}
        </section>
      )}
    </Panel>
  )
}
