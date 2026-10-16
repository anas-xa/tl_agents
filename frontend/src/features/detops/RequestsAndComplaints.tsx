import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Placeholder } from '../../components/Placeholder'
import { Button, Chip, Dialog, Empty, Field, Ident, Message, PageHeader, Panel, Skeleton, StatCard, Table, Tabs } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime, iso } from '../../lib/format'
import { daysUntil, dubaiToday, formatDubaiDate } from '../det/headerMeta'
import { DueChip, NextStep } from '../det/ui'

interface CaseRow { id: string; action: string; state: string; chip: string; reason_code: string | null; reference_code: string; received_at: string; effective_at: string | null; subscription_id: string; can_cancel: boolean }
interface ComplaintRow { id: string; reference: string; licence_number: string; category: string; received_at: string; reply_by: string; interim_due_date: string | null; status: string; status_reason_code: string | null; filed_for_owner: boolean; description: string; escalation_flag?: boolean }

const OPEN = new Set(['requested', 'pending_DET', 'needs_DET_action'])
const COMPLAINT_STATUSES = ['received', 'in_review', 'replied', 'resolved', 'refunded', 'rejected']
const DONE = new Set(['replied', 'resolved', 'refunded', 'rejected'])

/** DET staff queues: subscription opt-out/refund requests (det.cases.decide) and the complaint log (complaints.handle). */
export default function RequestsAndComplaints() {
  const { t, i18n } = useTranslation('detops')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { me } = useAuth()
  const canCases = !!me?.staff_permissions.includes('det.cases.decide')
  const canComplaints = !!me?.staff_permissions.includes('complaints.handle')
  const [tab, setTab] = useState<'requests' | 'complaints'>(canCases ? 'requests' : 'complaints')
  if (!me) return null
  if (!canCases && !canComplaints) return <Placeholder variant="C" />
  const both = canCases && canComplaints
  const body = (
    <>
      {tab === 'requests' && canCases && <Requests lang={lang} />}
      {tab === 'complaints' && canComplaints && <Complaints lang={lang} />}
    </>
  )
  return (
    <div className="page det-ws">
      <PageHeader eyebrow={t('eyebrow')} title={t('title')} subtitle={t('intro')} />
      {both ? (
        <>
          <Tabs
            label={t('title')}
            idPrefix="detops"
            value={tab}
            onChange={setTab}
            tabs={[{ id: 'requests' as const, label: t('tab_requests') }, { id: 'complaints' as const, label: t('tab_complaints') }]}
          />
          <div role="tabpanel" id={`detops-${tab}-panel`} aria-labelledby={`detops-${tab}`}>{body}</div>
        </>
      ) : body}
    </div>
  )
}

function Requests({ lang }: { lang: string }) {
  const { t } = useTranslation('detops')
  const [rows, setRows] = useState<CaseRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<CaseRow | null>(null)
  const [decision, setDecision] = useState<'confirm' | 'reject'>('confirm')
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => {
    get<{ cases: CaseRow[] }>('/api/det/cases').then((r) => setRows(r.cases)).catch((e) => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])
  const submit = async () => {
    if (!open) return
    try {
      await post(`/api/det/cases/${open.id}/decision`, { decision, reason: reason || null })
      setMsg(t('saved'))
      setOpen(null)
      setReason('')
      load()
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.message} (${e.code})` : (e as Error).message)
    }
  }
  if (err) return <Message kind="error">{err}</Message>
  if (!rows) return <Skeleton rows={4} />
  const waiting = rows.filter((c) => OPEN.has(c.state)).sort((x, y) => x.received_at.localeCompare(y.received_at))
  const applied = rows.filter((c) => c.chip === 'applied').length
  const refused = rows.filter((c) => c.chip === 'refused').length
  const first = waiting[0]
  const openDecide = (c: CaseRow) => { setOpen(c); setDecision('confirm') }
  return (
    <>
      <div className="stat-grid">
        <StatCard icon="inbox" tone={waiting.length ? 'attention' : 'ok'} label={t('stat_waiting')} value={<bdi dir="ltr">{waiting.length}</bdi>} hint={t('stat_waiting_hint')} />
        <StatCard icon="check" tone="ok" label={t('stat_applied')} value={<bdi dir="ltr">{applied}</bdi>} />
        <StatCard icon="close" label={t('stat_refused')} value={<bdi dir="ltr">{refused}</bdi>} />
      </div>
      {first ? (
        <NextStep action={<Button variant="secondary" className="det-rowbtn" onClick={() => openDecide(first)}>{t('decide')}</Button>}>
          {t('next_request', { ref: iso(first.reference_code), action: t(`action_${first.action}`, { defaultValue: first.action }), date: formatDateTime(first.received_at, lang) })}
        </NextStep>
      ) : (
        <NextStep tone="calm" icon="check">{t('next_request_none')}</NextStep>
      )}
      {msg && <Message kind="success">{msg}</Message>}
      <Panel title={t('tab_requests')} className="det-panel-flush" actions={<span className="hint">{t('count_n', { n: rows.length })}</span>}>
      {rows.length === 0 ? <Empty icon="inbox" title={t('empty_requests')} body={t('empty_requests_next')} /> : (
        <div className="table-compact det-table">
        <Table headers={[t('reference'), t('action'), t('received'), t('state'), t('effective'), <span className="visually-hidden" key="a">{t('col_action')}</span>]}>
          {rows.map((c) => (
            <tr key={c.id}>
              <td className="nowrap"><Ident>{c.reference_code}</Ident></td>
              <td className="nowrap">{t(`action_${c.action}`, { defaultValue: c.action })}</td>
              <td className="date-cell">{formatDateTime(c.received_at, lang)}</td>
              <td><Chip tone={c.chip === 'applied' ? 'ok' : c.chip === 'refused' ? 'critical' : c.chip === 'with_det' ? 'urgent' : 'info'}>{t(`case_chip.${c.chip}`)}</Chip></td>
              <td className="date-cell">{c.effective_at ? formatDubaiDate(c.effective_at, lang) : <span className="notice-tbc">{t('effective_tbc')}</span>}</td>
              <td className="nowrap">{OPEN.has(c.state) && <Button variant="secondary" className="det-rowbtn" onClick={() => openDecide(c)}>{t('decide')}</Button>}</td>
            </tr>
          ))}
        </Table>
        </div>
      )}
      </Panel>
      <Dialog open={!!open} title={t('decide')} onClose={() => setOpen(null)} labelledBy="decide-title">
        <fieldset style={{ border: 0, padding: 0 }}>
          <label style={{ display: 'block', minHeight: 44 }}><input type="radio" name="d" checked={decision === 'confirm'} onChange={() => setDecision('confirm')} /> {t('confirm')}</label>
          <label style={{ display: 'block', minHeight: 44 }}><input type="radio" name="d" checked={decision === 'reject'} onChange={() => setDecision('reject')} /> {t('reject')}</label>
        </fieldset>
        <Field label={t('reason')} id="decide-reason" required={decision === 'reject'}>
          <input id="decide-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <div className="actions">
          <Button onClick={submit} disabled={decision === 'reject' && !reason.trim()}>{t('decide')}</Button>
          <Button variant="secondary" onClick={() => setOpen(null)}>{t('common.cancel', { ns: 'translation' })}</Button>
        </div>
      </Dialog>
    </>
  )
}

function Complaints({ lang }: { lang: string }) {
  const { t } = useTranslation('detops')
  const [rows, setRows] = useState<ComplaintRow[] | null>(null)
  const [sla, setSla] = useState<number>(5)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<ComplaintRow | null>(null)
  const [form, setForm] = useState({ status: 'in_review', reason_code: '', interim_due_date: '' })
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => {
    get<{ complaints: ComplaintRow[]; sla_working_days: number }>('/api/det/complaints').then((r) => { setRows(r.complaints); setSla(r.sla_working_days) }).catch((e) => setErr(e.message))
  }, [])
  useEffect(() => { load() }, [load])
  const submit = async () => {
    if (!open) return
    try {
      await post(`/api/det/complaints/${open.id}/status`, { status: form.status, reason_code: form.reason_code, interim_due_date: form.interim_due_date || null })
      setMsg(t('saved'))
      setOpen(null)
      load()
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.message} (${e.code})` : (e as Error).message)
    }
  }
  if (err) return <Message kind="error">{err}</Message>
  if (!rows) return <Skeleton rows={4} />
  const today = dubaiToday()
  const isDone = (c: ComplaintRow) => DONE.has(c.status)
  const openRows = rows.filter((c) => !isDone(c)).sort((x, y) => x.reply_by.localeCompare(y.reply_by))
  const overdue = openRows.filter((c) => c.reply_by < today)
  const dueSoon = openRows.filter((c) => { const d = daysUntil(c.reply_by); return d !== null && d >= 0 && d <= 2 })
  const first = openRows[0]
  const openUpdate = (c: ComplaintRow) => { setOpen(c); setForm({ status: c.status === 'received' ? 'in_review' : c.status, reason_code: '', interim_due_date: '' }) }
  return (
    <>
      <div className="stat-grid">
        <StatCard icon="inbox" tone={openRows.length ? 'info' : 'ok'} label={t('stat_open')} value={<bdi dir="ltr">{openRows.length}</bdi>} hint={t('stat_open_hint', { n: rows.length })} />
        <StatCard icon="clock" tone={dueSoon.length ? 'urgent' : undefined} label={t('stat_due_soon')} value={<bdi dir="ltr">{dueSoon.length}</bdi>} hint={t('stat_due_soon_hint')} />
        <StatCard icon="alert" tone={overdue.length ? 'critical' : undefined} label={t('overdue')} value={<bdi dir="ltr">{overdue.length}</bdi>} />
        <StatCard icon="calendar" label={t('stat_target')} value={t('stat_target_value', { n: sla })} hint={t('stat_target_hint')} />
      </div>
      {first ? (
        <NextStep action={<Button variant="secondary" className="det-rowbtn" onClick={() => openUpdate(first)}>{t('set_status')}</Button>}>
          {first.reply_by < today ? t('next_complaint_overdue', { ref: iso(first.reference), date: formatDate(first.reply_by, lang) }) : t('next_complaint', { ref: iso(first.reference), date: formatDate(first.reply_by, lang) })}
        </NextStep>
      ) : (
        <NextStep tone="calm" icon="check">{t('next_complaint_none')}</NextStep>
      )}
      {msg && <Message kind="success">{msg}</Message>}
      <Panel title={t('tab_complaints')} className="det-panel-flush" actions={<span className="hint">{t('count_n', { n: rows.length })}</span>}>
      {rows.length === 0 ? <Empty icon="inbox" title={t('empty_complaints')} body={t('empty_complaints_next')} /> : (
        <div className="table-compact det-table">
        <Table headers={[t('reference'), t('licence'), t('category'), t('received'), t('reply_by'), t('state'), t('description'), <span className="visually-hidden" key="a">{t('col_action')}</span>]}>
          {rows.map((c) => (
            <tr key={c.id}>
              <td className="nowrap"><Ident>{c.reference}</Ident>{c.filed_for_owner && <span className="det-cell-sub">{t('filed_for_owner')}</span>}</td>
              <td className="nowrap"><Ident>{c.licence_number}</Ident></td>
              <td className="nowrap">{t(`category_${c.category}`, { defaultValue: c.category.replace(/_/g, ' ') })}</td>
              <td className="date-cell" title={formatDateTime(c.received_at, lang)}>{formatDubaiDate(c.received_at, lang)}</td>
              <td className="date-cell">
                {formatDate(c.reply_by, lang)}
                {!isDone(c) && <span className="det-cell-sub">{c.reply_by < today ? <Chip tone="critical" icon="!">{t('overdue')}</Chip> : <DueChip date={c.reply_by} />}</span>}
              </td>
              <td><Chip tone={c.status === 'resolved' || c.status === 'replied' || c.status === 'refunded' ? 'ok' : c.status === 'rejected' ? 'critical' : 'info'}>{t(`status.${c.status}`)}</Chip></td>
              <td className="det-wrap">{c.description}</td>
              <td className="nowrap"><Button variant="secondary" className="det-rowbtn" onClick={() => openUpdate(c)}>{t('set_status')}</Button></td>
            </tr>
          ))}
        </Table>
        </div>
      )}
      </Panel>
      <Dialog open={!!open} title={t('set_status')} onClose={() => setOpen(null)} labelledBy="complaint-title">
        <Field label={t('state')} id="c-status"><select id="c-status" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>{COMPLAINT_STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}</select></Field>
        <Field label={t('status_reason_code')} id="c-reason" required><input id="c-reason" value={form.reason_code} onChange={(e) => setForm({ ...form, reason_code: e.target.value })} /></Field>
        <Field label={t('interim_due')} id="c-interim"><input id="c-interim" type="date" value={form.interim_due_date} onChange={(e) => setForm({ ...form, interim_due_date: e.target.value })} /></Field>
        <div className="actions">
          <Button onClick={submit} disabled={!form.reason_code.trim()}>{t('set_status')}</Button>
          <Button variant="secondary" onClick={() => setOpen(null)}>{t('common.cancel', { ns: 'translation' })}</Button>
        </div>
      </Dialog>
    </>
  )
}
