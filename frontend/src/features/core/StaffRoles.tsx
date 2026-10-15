import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Field, Message, Panel, Skeleton, Table } from '../../components/ui'
import { get, post } from '../../lib/api'

interface Row { id: number; role: string; scope: string | null; work_email: string; status: string; requester: string; approver: string; bound: boolean; invitation_expires_at: string | null }

/** Staff-role administration: two-person approval, single-use invitations bound on first UAE PASS sign-in. */
export default function StaffRoles() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<Row[] | null>(null)
  const [form, setForm] = useState({ role: 'compliance_reviewer', work_email: '', approver: '', reason: '' })
  const [msg, setMsg] = useState<{ kind: 'info' | 'error'; text: string } | null>(null)
  const load = () => get<Row[]>('/api/admin/staff-roles').then(setRows).catch((e) => setMsg({ kind: 'error', text: e.message }))
  useEffect(() => { load() }, [])
  return (
    <div>
      <h1>Staff roles</h1>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <Panel title="Invite a staff member (two-person approval)">
        <form onSubmit={async (e) => { e.preventDefault(); try { const r = await post<{ invitation_token: string }>('/api/admin/staff-roles', form); setMsg({ kind: 'info', text: `Invitation created. Token (single use, 7 days): ${r.invitation_token}` }); load() } catch (err) { setMsg({ kind: 'error', text: (err as Error).message }) } }}>
          <Field label={t('common.role')} id="role"><select id="role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{['det_admin', 'det_pilot_manager', 'det_complaint_handler', 'det_compliance_lead', 'compliance_reviewer', 'licensed_auditor', 'tax_specialist', 'legal_specialist', 'escalation_ops', 'platform_security_admin', 'qeonix_product_owner', 'qeonix_audit_ops'].map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}</select></Field>
          <Field label="Work email" id="email" required><input id="email" type="email" required value={form.work_email} onChange={(e) => setForm({ ...form, work_email: e.target.value })} /></Field>
          <Field label="Approver (must be a different person)" id="approver" required><input id="approver" required value={form.approver} onChange={(e) => setForm({ ...form, approver: e.target.value })} /></Field>
          <Field label={t('common.reason')} id="reason"><input id="reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
          <Button type="submit">{t('common.add')}</Button>
        </form>
      </Panel>
      <Panel title="Staff-role table">
        {!rows ? <Skeleton /> : (
          <Table headers={['#', t('common.role'), 'Scope', 'Email', t('common.status'), 'Requester', 'Approver', 'Bound']}>
            {rows.map((r) => (
              <tr key={r.id}><td>{r.id}</td><td>{t(`roles.${r.role}`)}</td><td>{r.scope}</td><td><bdi dir="ltr">{r.work_email}</bdi></td><td><Chip tone={r.status === 'active' ? 'ok' : r.status === 'invited' ? 'attention' : 'neutral'}>{r.status}</Chip></td><td>{r.requester}</td><td>{r.approver}</td><td>{r.bound ? '✓' : '—'}</td></tr>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  )
}
