import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Dialog, Field, Message, PageHeader, Skeleton } from '../../components/ui'
import { Icon } from '../../components/Icon'
import { get, post } from '../../lib/api'
import { humanize } from './lib'
import './i18n'
import './core.css'

interface Row { id: number; role: string; scope: string | null; work_email: string; status: string; requester: string; approver: string; bound: boolean; invitation_expires_at: string | null }

const ROLES = ['det_admin', 'det_pilot_manager', 'det_complaint_handler', 'det_compliance_lead', 'compliance_reviewer', 'licensed_auditor', 'tax_specialist', 'legal_specialist', 'escalation_ops', 'platform_security_admin', 'qeonix_product_owner', 'qeonix_audit_ops']

/** Staff-role administration: two-person approval, single-use invitations bound on first UAE PASS sign-in. */
export default function StaffRoles() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<Row[] | null>(null)
  const [form, setForm] = useState({ role: 'compliance_reviewer', work_email: '', approver: '', reason: '' })
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [formErr, setFormErr] = useState<string | null>(null)
  const [inviting, setInviting] = useState(false)
  const load = () => get<Row[]>('/api/admin/staff-roles').then(setRows).catch((e) => setMsg({ kind: 'error', text: e.message }))
  useEffect(() => { load() }, [])
  const active = rows?.filter((r) => r.status === 'active').length ?? 0
  const invited = rows?.filter((r) => r.status === 'invited').length ?? 0
  const headers = ['#', t('common.role'), t('core:col_scope'), t('core:work_email'), t('common.status'), t('core:col_requester'), t('core:col_approver'), t('core:col_bound')]

  return (
    <div className="core-page">
      <PageHeader
        eyebrow={t('core:security_admin')}
        title={t('core:staff_title')}
        subtitle={t('core:staff_subtitle')}
        actions={<Button onClick={() => { setFormErr(null); setInviting(true) }}><Icon name="user" size={18} />{t('core:invite')}</Button>}
        meta={rows && (
          <>
            <Chip tone="ok">{t('core:n_active', { count: active })}</Chip>
            {invited > 0 && <Chip tone="attention">{t('core:n_invited', { count: invited })}</Chip>}
          </>
        )}
      />
      {msg && <Message kind={msg.kind}>{msg.kind === 'success' ? <span className="core-break">{msg.text}</span> : msg.text}</Message>}

      <section className="panel core-table-panel" aria-labelledby="staff-table">
        <header className="panel-header"><h2 id="staff-table">{t('core:staff_table')}</h2></header>
        {!rows ? <div className="panel-body"><Skeleton /></div> : (
          <div className="table-wrap core-table-wrap">
            <table className="table-compact core-table core-stack">
              <thead><tr>{headers.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td data-label={headers[0]} className="num muted">{r.id}</td>
                    <td data-label={headers[1]}>{t(`roles.${r.role}`, { defaultValue: humanize(r.role) })}</td>
                    <td data-label={headers[2]}>{r.scope ? t(`core:scope_${r.scope}`, { defaultValue: r.scope }) : '—'}</td>
                    <td data-label={headers[3]}><bdi dir="ltr" className="core-break">{r.work_email}</bdi></td>
                    <td data-label={headers[4]}><Chip tone={r.status === 'active' ? 'ok' : r.status === 'invited' ? 'attention' : 'neutral'}>{t(`core:staff_status.${r.status}`, { defaultValue: humanize(r.status) })}</Chip></td>
                    <td data-label={headers[5]}><bdi dir="ltr" className="core-mono">{r.requester}</bdi></td>
                    <td data-label={headers[6]}><bdi dir="ltr" className="core-mono">{r.approver}</bdi></td>
                    <td data-label={headers[7]}>
                      {r.bound
                        ? <span className="core-bound core-bound-yes"><Icon name="check" size={16} />{t('core:bound_yes')}</span>
                        : <span className="core-bound muted"><Icon name="clock" size={16} />{t('core:bound_no')}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Dialog open={inviting} title={t('core:invite_title')} onClose={() => setInviting(false)} labelledBy="staff-invite-title">
        {formErr && <Message kind="error">{formErr}</Message>}
        <form
          className="core-dialog-form"
          onSubmit={async (e) => {
            e.preventDefault()
            try {
              const r = await post<{ invitation_token: string }>('/api/admin/staff-roles', form)
              setMsg({ kind: 'success', text: t('core:invite_created', { token: r.invitation_token }) })
              setInviting(false)
              setForm({ role: 'compliance_reviewer', work_email: '', approver: '', reason: '' })
              load()
            } catch (err) {
              setFormErr((err as Error).message)
            }
          }}
        >
          <Field label={t('common.role')} id="role">
            <select id="role" autoFocus value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}</select>
          </Field>
          <Field label={t('core:work_email')} id="email" required><input id="email" type="email" dir="ltr" required value={form.work_email} onChange={(e) => setForm({ ...form, work_email: e.target.value })} /></Field>
          <Field label={t('core:approver')} id="approver" required><input id="approver" required value={form.approver} onChange={(e) => setForm({ ...form, approver: e.target.value })} /></Field>
          <Field label={t('common.reason')} id="reason"><input id="reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
          <div className="dialog-actions">
            <Button type="button" variant="secondary" onClick={() => setInviting(false)}>{t('common.cancel')}</Button>
            <Button type="submit">{t('common.add')}</Button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}
