import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Placeholder } from '../../components/Placeholder'
import { Button, Chip, Dialog, Empty, Field, Ident, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get, post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'

interface CaseRow { id: string; action: string; state: string; chip: string; reason_code: string | null; reference_code: string; received_at: string; effective_at: string | null; subscription_id: string; can_cancel: boolean }
interface ComplaintRow { id: string; reference: string; licence_number: string; category: string; received_at: string; reply_by: string; interim_due_date: string | null; status: string; status_reason_code: string | null; filed_for_owner: boolean; description: string; escalation_flag?: boolean }

const OPEN = new Set(['requested', 'pending_DET', 'needs_DET_action'])
const COMPLAINT_STATUSES = ['received', 'in_review', 'replied', 'resolved', 'refunded', 'rejected']

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
  return (
    <div>
      <h1>{t('title')}</h1>
      <p className="muted">{t('intro')}</p>
      <div className="tabs" role="tablist">
        {canCases && <button role="tab" aria-selected={tab === 'requests'} onClick={() => setTab('requests')}>{t('tab_requests')}</button>}
        {canComplaints && <button role="tab" aria-selected={tab === 'complaints'} onClick={() => setTab('complaints')}>{t('tab_complaints')}</button>}
      </div>
      {tab === 'requests' && canCases && <Requests lang={lang} />}
      {tab === 'complaints' && canComplaints && <Complaints lang={lang} />}
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
  return (
    <Panel title={t('tab_requests')}>
      {msg && <Message kind="success">{msg}</Message>}
      {rows.length === 0 ? <Empty title={t('empty_requests')} /> : (
        <Table headers={[t('reference'), t('action'), t('received'), t('state'), t('effective'), '']}>
          {rows.map((c) => (
            <tr key={c.id}>
              <td><Ident>{c.reference_code}</Ident></td>
              <td>{t(`action_${c.action}`, { defaultValue: c.action })}</td>
              <td>{formatDateTime(c.received_at, lang)}</td>
              <td><Chip tone={c.chip === 'applied' ? 'ok' : c.chip === 'refused' ? 'critical' : c.chip === 'with_det' ? 'urgent' : 'info'}>{t(`case_chip.${c.chip}`)}</Chip></td>
              <td>{c.effective_at ? formatDate(c.effective_at, lang) : <span className="notice-tbc">{t('effective_tbc')}</span>}</td>
              <td>{OPEN.has(c.state) && <Button variant="secondary" onClick={() => { setOpen(c); setDecision('confirm') }}>{t('decide')}</Button>}</td>
            </tr>
          ))}
        </Table>
      )}
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
    </Panel>
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
  const today = new Date().toISOString().slice(0, 10)
  return (
    <Panel title={t('tab_complaints')}>
      <p className="muted">{t('reply_target', { n: sla })}</p>
      {msg && <Message kind="success">{msg}</Message>}
      {rows.length === 0 ? <Empty title={t('empty_complaints')} /> : (
        <Table headers={[t('reference'), t('licence'), t('category'), t('received'), t('reply_by'), t('state'), t('description'), '']}>
          {rows.map((c) => {
            const overdue = !['replied', 'resolved', 'refunded', 'rejected'].includes(c.status) && c.reply_by < today
            return (
              <tr key={c.id}>
                <td><Ident>{c.reference}</Ident></td>
                <td><Ident>{c.licence_number}</Ident></td>
                <td>{c.category}</td>
                <td>{formatDateTime(c.received_at, lang)}</td>
                <td>{formatDate(c.reply_by, lang)} {overdue && <Chip tone="critical">{t('overdue')}</Chip>}</td>
                <td><Chip tone={c.status === 'resolved' || c.status === 'replied' ? 'ok' : c.status === 'rejected' ? 'critical' : 'info'}>{t(`status.${c.status}`)}</Chip>{c.filed_for_owner && <div className="muted">{t('filed_for_owner')}</div>}</td>
                <td style={{ maxWidth: 280 }}>{c.description}</td>
                <td><Button variant="secondary" onClick={() => { setOpen(c); setForm({ status: c.status === 'received' ? 'in_review' : c.status, reason_code: '', interim_due_date: '' }) }}>{t('set_status')}</Button></td>
              </tr>
            )
          })}
        </Table>
      )}
      <Dialog open={!!open} title={t('set_status')} onClose={() => setOpen(null)} labelledBy="complaint-title">
        <Field label={t('state')} id="c-status"><select id="c-status" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>{COMPLAINT_STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}</select></Field>
        <Field label={t('status_reason_code')} id="c-reason" required><input id="c-reason" value={form.reason_code} onChange={(e) => setForm({ ...form, reason_code: e.target.value })} /></Field>
        <Field label={t('interim_due')} id="c-interim"><input id="c-interim" type="date" value={form.interim_due_date} onChange={(e) => setForm({ ...form, interim_due_date: e.target.value })} /></Field>
        <div className="actions">
          <Button onClick={submit} disabled={!form.reason_code.trim()}>{t('set_status')}</Button>
          <Button variant="secondary" onClick={() => setOpen(null)}>{t('common.cancel', { ns: 'translation' })}</Button>
        </div>
      </Dialog>
    </Panel>
  )
}
