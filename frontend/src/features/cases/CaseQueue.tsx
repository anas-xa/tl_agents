import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip, Empty, Field, Ident, Message, PageHeader, Panel, Skeleton, StatCard, Table, Tabs } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime, iso } from '../../lib/format'
import { formatDubaiDate } from '../det/headerMeta'
import { NextStep } from '../det/ui'

type Bi = { en: string; ar: string }
interface Meta { case_id: string; module: string; priority: string; status: string; escalation_reason: string; queue: string; specialist_type: string; assigned: boolean; assigned_role_label: string | null; flags: string[]; escalated_at: string; consent_decision: string | null; consent_requested_at: string | null; due_date: string | null; turnaround: { active_working_days: number; raw_working_days: number; paused_now: boolean }; is_demo: boolean }
interface Alert { id: string; type: string; case_id: string | null; created_at: string; recipients: string[]; escalated_to_pilot_manager: boolean }
interface Queue { mode: 'specialist' | 'ops'; specialist_type?: string; cases: Meta[]; unassigned?: Meta[]; alerts?: Alert[]; tax_path_enabled: boolean; lawyer_path_enabled: boolean }
interface Detail { mode: 'specialist' | 'ops'; case_id?: string; case_type?: string; escalation_reason?: string; deadline?: string | null; priority?: string; company_ref?: string; title?: string | null; status?: string; consent_decision?: string | null; locked_items?: { item: string; locked: boolean; cause: string }[]; metadata: Meta; access_log?: { who: string; role: string; what: string; when: string; result: string; reason: string | null }[]; consent_wait: { day: number; reminder_days: number[]; ops_alert_day: number; close_day: number; reopen_window: number; decision: string | null } | null; candidates?: { identity_uuid: string; status: string; valid_to: string | null; register: string; firm_agreement_signed: boolean }[] }

const SCOPE_ITEMS = ['return', 'tax profile', 'audit file', 'invoice', 'bank statement', 'ledger']

const CLOSED = ['rejected', 'resolved', 'closed', 'closed_no_consent']
const statusTone = (s: string) => (s === 'resolved' ? 'ok' : s === 'awaiting_consent' ? 'attention' : CLOSED.includes(s) ? 'neutral' : 'info')

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
  const mine = q?.cases ?? []
  const open = mine.filter((c) => !CLOSED.includes(c.status))
  const waitingConsent = open.filter((c) => c.status === 'awaiting_consent').length
  const near = open.filter((c) => c.priority === 'deadline_near').length
  const next = [...open].sort((x, y) => (x.priority === y.priority ? x.escalated_at.localeCompare(y.escalated_at) : x.priority === 'deadline_near' ? -1 : 1))[0]
  const tabs: { id: 'mine' | 'unassigned' | 'alerts'; label: string; badge?: number }[] = [{ id: 'mine', label: t('tabs.mine'), badge: mine.length }]
  if (q?.mode === 'specialist') tabs.push({ id: 'unassigned', label: t('tabs.unassigned'), badge: q.unassigned?.length ?? 0 })
  if (q?.mode === 'ops') tabs.push({ id: 'alerts', label: t('tabs.alerts'), badge: q.alerts?.length ?? 0 })
  return (
    <div className="page det-ws">
      <PageHeader
        eyebrow={t(q?.mode === 'ops' ? 'eyebrow_ops' : 'eyebrow')}
        title={t('title')}
        subtitle={q ? t(`mode.${q.mode}`) : undefined}
        meta={<Chip tone="draft" icon="✎">{t('ai_label')}</Chip>}
      />
      {q && q.mode === 'specialist' && ((q.specialist_type === 'tax' && !q.tax_path_enabled) || (q.specialist_type === 'lawyer' && !q.lawyer_path_enabled)) && <Message kind="warning">{t('path_off')}</Message>}
      {err && <Message kind="error">{t('error')}</Message>}
      {sel ? (
        <>
          <div className="det-back"><Button variant="link" className="btn-ghost" onClick={() => { setSel(null); load() }}><Icon name="chevron-start" size={18} className="flip-rtl" />{t('back')}</Button></div>
          <CaseDetail id={sel} lang={lang} onBack={() => { setSel(null); load() }} />
        </>
      ) : (
        <>
          {!q && !err && (<><p className="visually-hidden" role="status">{t('loading')}</p><div className="stat-grid">{[0, 1, 2].map((i) => <div key={i} className="card"><Skeleton rows={2} /></div>)}</div><Skeleton /></>)}
          {q && (
            <>
              <div className="stat-grid">
                <StatCard icon="inbox" label={t('stats.assigned')} value={<bdi dir="ltr">{mine.length}</bdi>} hint={t('stats.assigned_hint', { n: open.length })} />
                <StatCard icon="lock" tone={waitingConsent ? 'attention' : undefined} label={t('stats.consent')} value={<bdi dir="ltr">{waitingConsent}</bdi>} hint={t('stats.consent_hint')} />
                <StatCard icon="clock" tone={near ? 'urgent' : undefined} label={t('stats.deadline')} value={<bdi dir="ltr">{near}</bdi>} hint={t('stats.deadline_hint')} />
                {q.mode === 'specialist' && <StatCard icon="users" label={t('tabs.unassigned')} value={<bdi dir="ltr">{q.unassigned?.length ?? 0}</bdi>} />}
                {q.mode === 'ops' && <StatCard icon="bell" tone={(q.alerts ?? []).length ? 'attention' : undefined} label={t('tabs.alerts')} value={<bdi dir="ltr">{q.alerts?.length ?? 0}</bdi>} />}
              </div>
              {next ? (
                <NextStep action={<Button variant="secondary" className="det-rowbtn" onClick={() => setSel(next.case_id)}>{t('open_case')}</Button>}>
                  {t('next', { ref: iso(next.case_id.slice(0, 13)), status: t(`status.${next.status}`), date: formatDateTime(next.escalated_at, lang) })}
                </NextStep>
              ) : (
                <NextStep tone="calm" icon="check">{t('next_none')}</NextStep>
              )}
              <Tabs label={t('title')} idPrefix="cases" value={tab} onChange={setTab} tabs={tabs} />
            </>
          )}
          <div role="tabpanel" id={`cases-${tab}-panel`} aria-labelledby={`cases-${tab}`}>
          {q && tab !== 'alerts' && (rows.length === 0 ? <Empty icon="inbox" title={t(tab === 'mine' ? 'empty_mine' : 'empty_unassigned')} body={t('empty_next')} /> : (
            <div className="panel det-panel-flush"><div className="table-compact det-table">
            <Table headers={[t('cols.case'), t('cols.module'), t('cols.priority'), t('cols.status'), t('cols.reason'), t('cols.escalated'), t('cols.turnaround'), <span key="a" className="visually-hidden">{t('cols.action')}</span>]}>
              {rows.map((c) => (
                <tr key={c.case_id}>
                  <td className="nowrap">
                    <button type="button" className="btn btn-link det-ref-btn" onClick={() => setSel(c.case_id)}><Ident>{c.case_id.slice(0, 13)}</Ident></button>
                    {c.flags.length > 0 && <span className="det-cell-sub">{c.flags.map((f) => <Chip key={f} tone="attention" icon="!">{t(`flags.${f}`, { defaultValue: f })}</Chip>)}</span>}
                  </td>
                  <td className="nowrap">{t(`module.${c.module}`, { defaultValue: c.module })}</td>
                  <td><Chip tone={c.priority === 'deadline_near' ? 'urgent' : 'neutral'}>{t(`priority.${c.priority}`)}</Chip></td>
                  <td><Chip tone={statusTone(c.status)}>{t(`status.${c.status}`)}</Chip></td>
                  <td className="nowrap">{t(`reason.${c.escalation_reason}`, { defaultValue: c.escalation_reason.replace(/_/g, ' ') })}</td>
                  <td className="date-cell" title={formatDateTime(c.escalated_at, lang)}>{formatDubaiDate(c.escalated_at, lang)}</td>
                  <td className="nowrap num"><bdi dir="ltr">{c.turnaround.active_working_days} / {c.turnaround.raw_working_days}</bdi>{c.turnaround.paused_now && <> <Chip tone="neutral" icon="⏸">{t('paused')}</Chip></>}</td>
                  <td className="nowrap"><Button variant="secondary" className="det-rowbtn" onClick={() => setSel(c.case_id)}>{t('open_case')}</Button></td>
                </tr>
              ))}
            </Table>
            </div></div>
          ))}
          {q && tab === 'alerts' && ((q.alerts ?? []).length === 0 ? <Empty icon="bell" title={t('empty_alerts')} body={t('empty_next')} /> : (
            <div className="panel det-panel-flush"><div className="table-compact det-table">
            <Table headers={[t('alerts.type'), t('alerts.case'), t('alerts.created'), <span key="a" className="visually-hidden">{t('cols.action')}</span>]}>
              {(q.alerts ?? []).map((a) => (
                <tr key={a.id}>
                  <td><Ident>{a.type}</Ident> {a.escalated_to_pilot_manager && <Chip tone="urgent" icon="!">{t('alerts.escalated')}</Chip>}</td>
                  <td className="nowrap">{a.case_id ? <button type="button" className="btn btn-link det-ref-btn" onClick={() => setSel(a.case_id!)}><Ident>{a.case_id.slice(0, 13)}</Ident></button> : '—'}</td>
                  <td className="date-cell">{formatDateTime(a.created_at, lang)}</td>
                  <td className="nowrap"><Button variant="secondary" className="det-rowbtn" onClick={() => post(`/api/cases/alerts/${a.id}/acknowledge`).then(load)}>{t('actions.acknowledge')}</Button></td>
                </tr>
              ))}
            </Table>
            </div></div>
          ))}
          </div>
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
  if (!d) return <Message kind="error">{err === 'NOT_ASSIGNED' ? 'You no longer have access to this case.' : t('error')} <Button variant="link" onClick={onBack}>{t('back')}</Button></Message>
  const m = d.metadata
  const closed = CLOSED.includes(m.status)
  const cw = d.consent_wait
  return (
    <div className="det-case">
      <div className="det-section-head is-first">
        <div className="det-section-head-text">
          <h2 id="case-title"><Ident>{id}</Ident></h2>
          <p className="det-exc-sub">
            <span>{t(`module.${m.module}`, { defaultValue: m.module })}</span>
            <Chip tone={m.priority === 'deadline_near' ? 'urgent' : 'neutral'}>{t(`priority.${m.priority}`)}</Chip>
            <Chip tone={statusTone(m.status)}>{t(`status.${m.status}`)}</Chip>
            {m.turnaround.paused_now && <Chip tone="neutral" icon="⏸">{t('paused')}</Chip>}
          </p>
        </div>
      </div>
      {err && <Message kind="error"><Ident>{err}</Ident>{err.startsWith('ENTITLEMENT') || err.endsWith('SWITCHED_OFF') ? ` · ${t('path_off')}` : ''}</Message>}
      {msg && <Message kind="success"><Ident>{msg}</Ident></Message>}
      {label && <Message kind="info"><strong>{t('output_label')}:</strong> {label[lang as 'en' | 'ar']} <Chip tone="draft" icon="✎">{t('ai_label')}</Chip></Message>}
      <dl className="det-facts">
        <div><dt>{t('cols.escalated')}</dt><dd>{formatDateTime(m.escalated_at, lang)}</dd></div>
        <div><dt>{t('cols.reason')}</dt><dd>{t(`reason.${m.escalation_reason}`, { defaultValue: m.escalation_reason.replace(/_/g, ' ') })}</dd></div>
        <div><dt>{t('cols.turnaround')}</dt><dd><bdi dir="ltr">{m.turnaround.active_working_days} / {m.turnaround.raw_working_days}</bdi></dd></div>
        <div><dt>{t('summary.deadline')}</dt><dd className="nowrap">{m.due_date ? formatDate(m.due_date, lang) : d.deadline ? formatDate(d.deadline, lang) : '—'}</dd></div>
      </dl>
      <div className="det-two">
        <div className="det-stack">
          {d.mode === 'specialist' && (
            <Panel title={t('summary.title')} id="case-summary">
              <p className="det-note"><Icon name="lock" size={16} />{t('summary.hint')}</p>
              <dl className="kv">
                <dt>{t('summary.reference')}</dt><dd><Ident>{d.case_id}</Ident></dd>
                <dt>{t('summary.type')}</dt><dd>{d.case_type}</dd>
                <dt>{t('summary.reason')}</dt><dd><Ident>{d.escalation_reason}</Ident></dd>
                <dt>{t('summary.deadline')}</dt><dd>{d.deadline ? formatDate(d.deadline, lang) : '—'}</dd>
                <dt>{t('summary.priority')}</dt><dd>{t(`priority.${d.priority}`)}</dd>
                <dt>{t('summary.company')}</dt><dd><Ident>{d.company_ref}</Ident></dd>
                <dt>{t('summary.owner_title')}</dt><dd>{d.title ?? '—'}</dd>
              </dl>
              {(d.locked_items ?? []).length > 0 && (
                <ul className="det-scope-items det-subsection">
                  {(d.locked_items ?? []).map((it) => (
                    <li key={it.item}>
                      <Chip tone={d.consent_decision === 'granted' ? 'ok' : 'neutral'} icon={d.consent_decision === 'granted' ? '✓' : '🔒'}>{t(`scope_items.${it.item}`, { defaultValue: it.item })}{d.consent_decision !== 'granted' ? ` · ${t('summary.locked')}` : ''}</Chip>
                      <Button variant="link" aria-disabled={d.consent_decision !== 'granted'} onClick={() => openItem(it.item)}>{t('summary.open_item')}</Button>
                      {itemState[it.item] === 'checking' && <span aria-live="polite" className="hint">{t('summary.checking')}</span>}
                      {itemState[it.item] === 'opened' && <span className="hint">{t('summary.opened')}</span>}
                      {itemState[it.item] && itemState[it.item] !== 'checking' && itemState[it.item] !== 'opened' && <Message kind="error">{t('summary.no_access')} <Ident>{itemState[it.item]}</Ident></Message>}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          )}
          {cw && (
            <Panel title={t('consent_wait.title')} id="case-consent">
              <p>{t('consent_wait.day', { day: cw.day })} · {t('consent_wait.decision')}: {cw.decision ?? '—'}</p>
              <ol className="det-timeline-steps">
                {cw.reminder_days.map((dd) => <li key={dd}><span className={`det-dot ${cw.day >= dd ? 'is-done' : ''}`} aria-hidden="true" />{t('consent_wait.reminder', { day: dd })}{cw.day >= dd ? ' ✓' : ''}</li>)}
                <li><span className={`det-dot ${cw.day >= cw.ops_alert_day ? 'is-done' : ''}`} aria-hidden="true" />{t('consent_wait.ops', { day: cw.ops_alert_day })}{cw.day >= cw.ops_alert_day ? ' ✓' : ''}</li>
                <li><span className={`det-dot ${m.status === 'closed_no_consent' ? 'is-done' : ''}`} aria-hidden="true" />{t('consent_wait.close', { day: cw.close_day })}{m.status === 'closed_no_consent' ? ' ✓' : ''}</li>
                <li><span className="det-dot" aria-hidden="true" />{t('consent_wait.reopen', { days: cw.reopen_window })}</li>
              </ol>
              {d.mode === 'ops' && <div className="actions"><Button variant="secondary" onClick={() => act('consent-wait/run')}>{t('consent_wait.run')}</Button></div>}
            </Panel>
          )}
          {d.access_log && (
            <Panel title={t('access_log.title')} id="case-log" className={d.access_log.length ? 'det-panel-flush' : undefined}>
              {d.access_log.length === 0 ? <p className="det-note"><Icon name="info" size={16} />{t('access_log.empty')}</p> : (
                <div className="table-compact det-table">
                <Table headers={[t('access_log.who'), t('access_log.what'), t('access_log.when'), t('access_log.result')]}>
                  {d.access_log.map((r, i) => <tr key={i}><td className="nowrap"><Ident>{r.who}</Ident></td><td>{r.what}</td><td className="date-cell">{formatDateTime(r.when, lang)}</td><td><Chip tone={r.result === 'Allowed' ? 'ok' : 'critical'}>{r.result}{r.reason ? ` · ${r.reason}` : ''}</Chip></td></tr>)}
                </Table>
                </div>
              )}
            </Panel>
          )}
        </div>
        {!closed ? (
          <Panel title={t('actions.title')} id="case-actions">
            {d.mode === 'ops' && (
              <form className="det-subsection" onSubmit={(e) => { e.preventDefault(); act('assign', { assignee_uuid: assignee }) }}>
                <Field label={t('actions.assignee')} id="assignee">
                  <select id="assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                    <option value="">—</option>
                    {(d.candidates ?? []).map((c) => <option key={c.identity_uuid} value={c.identity_uuid}>{c.identity_uuid} · {c.register} · {c.status}{c.valid_to ? ` · ${formatDate(c.valid_to, lang)}` : ''}</option>)}
                  </select>
                </Field>
                <Button type="submit" disabled={!assignee}>{m.assigned ? t('actions.reassign') : t('actions.assign')}</Button>
              </form>
            )}
            {d.mode === 'specialist' && (
              <>
                <fieldset className="det-subsection">
                  <legend>{t('actions.accept_scope')}</legend>
                  {SCOPE_ITEMS.map((s) => <label key={s} className="checkbox"><input type="checkbox" checked={scope.includes(s)} onChange={(e) => setScope((x) => (e.target.checked ? [...x, s] : x.filter((y) => y !== s)))} /> {t(`scope_items.${s}`)}</label>)}
                  <div className="actions"><Button onClick={() => act('accept', { requested_scope: scope.map((s) => ({ module: m.module, data_class: s })), purpose: 'case review' })}>{t('actions.accept')}</Button></div>
                </fieldset>
                <div className="det-subsection"><Button variant="secondary" onClick={() => act('first-response', {})}>{t('actions.first_response')}</Button></div>
                <form className="det-subsection" onSubmit={(e) => { e.preventDefault(); act('request-info', { request_code: reqCode }) }}>
                  <Field label={t('actions.request_code')} id="req-code"><input id="req-code" value={reqCode} onChange={(e) => setReqCode(e.target.value)} maxLength={40} dir="ltr" /></Field>
                  <Button type="submit" variant="secondary" disabled={!reqCode}>{t('actions.request_info')}</Button>
                </form>
                <form className="det-subsection" onSubmit={(e) => { e.preventDefault(); act('resolve', { outcome, limitation }) }}>
                  <Field label={t('actions.outcome')} id="outcome">
                    <select id="outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>{['a', 'b', 'c'].map((o) => <option key={o} value={o}>{t(`actions.outcomes.${o}`)}</option>)}</select>
                  </Field>
                  <label className="checkbox"><input type="checkbox" checked={limitation} onChange={(e) => setLimitation(e.target.checked)} /> {t('actions.limitation')}</label>
                  <div className="actions"><Button type="submit">{t('actions.resolve')}</Button></div>
                </form>
                {m.flags.includes('manual_review_key_incomplete') && (
                  <form className="det-subsection" onSubmit={(e) => { e.preventDefault(); act('complete-key', { matter_key: key }) }}>
                    <Field label={t('actions.complete_key')} id="mk"><input id="mk" value={key} onChange={(e) => setKey(e.target.value)} dir="ltr" /></Field>
                    <Button type="submit" variant="secondary" disabled={!key}>{t('actions.complete_key')}</Button>
                  </form>
                )}
              </>
            )}
            <form className="det-subsection" onSubmit={(e) => { e.preventDefault(); act('close', { reason_code: closeCode }) }}>
              <Field label={t('actions.close')} id="close-code">
                <select id="close-code" value={closeCode} onChange={(e) => setCloseCode(e.target.value)}>{['key_incomplete_closed', 'duplicate', 'not_in_scope', 'withdrawn_by_ops'].map((c) => <option key={c} value={c}>{t(`actions.close_codes.${c}`)}</option>)}</select>
              </Field>
              <Button type="submit" variant="danger">{t('actions.close')}</Button>
            </form>
          </Panel>
        ) : (
          <Panel title={t('actions.title')} id="case-actions">
            <p className="det-note"><Icon name="check" size={16} />{t('closed_note')}</p>
          </Panel>
        )}
      </div>
    </div>
  )
}
