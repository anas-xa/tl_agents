import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Chip, Message, Panel, Skeleton, Table } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { get, post } from '../../lib/api'

interface Ev { event_id: string; occurred_at: string; event_type: string; category: string; outcome: string; reason_code: string | null; actor_key?: string | null; actor_role: string | null; company_id?: string | null; subject_type: string | null; subject_id?: string | null; details?: Record<string, unknown> | null; hash: string }

/** SC15 Audit trail viewer: read-only, filterable; masked fields show 'Hidden for your role'; export needs a reason and a second approver. */
export default function AuditTrail() {
  const { t, i18n } = useTranslation()
  const { hasStaff } = useAuth()
  const [events, setEvents] = useState<Ev[] | null>(null)
  const [integrity, setIntegrity] = useState<{ intact: boolean; events_checked: number } | null>(null)
  const [filters, setFilters] = useState({ category: '', event_type: '', company_id: '' })
  const [err, setErr] = useState<string | null>(null)
  const [exportMsg, setExportMsg] = useState<string | null>(null)
  const load = useCallback(() => {
    const qs = new URLSearchParams(Object.fromEntries(Object.entries(filters).filter(([, v]) => v))).toString()
    get<{ events: Ev[] }>(`/api/admin/audit-trail?${qs}`).then((r) => setEvents(r.events)).catch((e) => setErr(e.message))
    get<{ intact: boolean; events_checked: number }>('/api/admin/audit-trail/integrity').then(setIntegrity).catch(() => setIntegrity(null))
  }, [filters])
  useEffect(() => { load() }, [load])
  const summaryOnly = hasStaff('det_admin') && !hasStaff('compliance_reviewer', 'platform_security_admin')
  return (
    <div>
      <h1>{t('nav.audit_trail')}</h1>
      {integrity && !integrity.intact && <Message kind="error">Integrity check failed. Some records may have been altered or are missing. Do not rely on this view for conclusions. Report to the platform security lead.</Message>}
      {integrity && integrity.intact && <p className="muted" role="status">Integrity check passed ({integrity.events_checked} events), {formatDateTime(new Date(), i18n.language)}</p>}
      {err && <Message kind="error">{err}</Message>}
      <div className="panel"><div className="panel-body" role="toolbar" aria-label={t('common.filter')} style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <label>Category <select value={filters.category} onChange={(e) => setFilters({ ...filters, category: e.target.value })}><option value="">—</option>{['sign_in', 'access', 'agent', 'consent', 'approval', 'escalation', 'sign_off', 'config', 'data_access', 'billing', 'document', 'reminder', 'system'].map((c) => <option key={c}>{c}</option>)}</select></label>
        <label>Event type <input value={filters.event_type} onChange={(e) => setFilters({ ...filters, event_type: e.target.value.toUpperCase() })} /></label>
        {!summaryOnly && <label>Company <input value={filters.company_id} onChange={(e) => setFilters({ ...filters, company_id: e.target.value })} /></label>}
        <Button variant="secondary" onClick={() => setFilters({ category: '', event_type: '', company_id: '' })}>{t('common.clear_filters')}</Button>
        {!summaryOnly && hasStaff('compliance_reviewer') && (
          <Button variant="secondary" onClick={async () => {
            try { const r = await post<{ export_id: string; row_count: number }>('/api/admin/audit-trail/export', { reason_code: 'internal_audit', approved_by_key: 'second-approver', pseudonymised: true, filters: { limit: 1000 } }); setExportMsg(`${t('common.export')}: ${r.export_id} (${r.row_count})`) } catch (e) { setExportMsg((e as Error).message) }
          }}>{t('common.export')}</Button>
        )}
      </div></div>
      {exportMsg && <Message kind="info">{exportMsg}</Message>}
      <Panel title={events ? t('common.records_found', { count: events.length }) : t('shell.loading')}>
        {!events ? <Skeleton rows={6} /> : (
          <Table headers={[t('common.date'), 'Event', 'Category', 'Outcome', 'Reason', 'Actor', t('common.company'), 'Subject', t('common.details'), 'Hash']}>
            {events.map((e) => (
              <tr key={e.event_id}>
                <td>{formatDateTime(e.occurred_at, i18n.language)}</td>
                <td><bdi dir="ltr">{e.event_type}</bdi></td>
                <td>{e.category}</td>
                <td><Chip tone={e.outcome === 'success' ? 'ok' : e.outcome === 'refused' ? 'critical' : 'neutral'}>{e.outcome}</Chip></td>
                <td><bdi dir="ltr">{e.reason_code ?? ''}</bdi></td>
                <td>{summaryOnly ? <span className="muted">{t('status.hidden_for_role')}</span> : <bdi dir="ltr">{(e.actor_key ?? '').slice(0, 10)}</bdi>}{e.actor_role ? ` · ${e.actor_role}` : ''}</td>
                <td>{summaryOnly ? <span className="muted">{t('status.hidden_for_role')}</span> : <bdi dir="ltr">{e.company_id ?? ''}</bdi>}</td>
                <td>{e.subject_type ?? ''} {summaryOnly ? '' : <bdi dir="ltr">{e.subject_id ?? ''}</bdi>}</td>
                <td>{summaryOnly ? <span className="muted">{t('status.hidden_for_role')}</span> : <details><summary>{t('common.details')}</summary><pre className="code">{JSON.stringify(e.details, null, 1)}</pre></details>}</td>
                <td><bdi dir="ltr">{e.hash.slice(0, 10)}</bdi></td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  )
}
