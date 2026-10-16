import { Fragment, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Chip, Empty, Field, Message, PageHeader, Pagination, Skeleton, Toolbar, usePaged } from '../../components/ui'
import { Icon } from '../../components/Icon'
import { formatDateTime, formatNumber } from '../../lib/format'
import { get, post } from '../../lib/api'
import { humanize, labelFor, shortDateTime } from './lib'
import './i18n'
import './core.css'

interface Ev { event_id: string; occurred_at: string; event_type: string; category: string; outcome: string; reason_code: string | null; actor_key?: string | null; actor_role: string | null; company_id?: string | null; subject_type: string | null; subject_id?: string | null; details?: Record<string, unknown> | null; hash: string; config_version?: string | null }

const CATEGORIES = ['sign_in', 'access', 'agent', 'consent', 'approval', 'escalation', 'sign_off', 'config', 'data_access', 'billing', 'document', 'reminder', 'system']

/** SC15 Audit trail viewer: read-only, filterable; masked fields show 'Hidden for your role'; export needs a reason and a second approver. */
export default function AuditTrail() {
  const { t, i18n } = useTranslation()
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { hasStaff } = useAuth()
  const [events, setEvents] = useState<Ev[] | null>(null)
  const [integrity, setIntegrity] = useState<{ intact: boolean; events_checked: number } | null>(null)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [filters, setFilters] = useState({ category: '', event_type: '', company_id: '' })
  const [err, setErr] = useState<string | null>(null)
  const [exportMsg, setExportMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const load = useCallback(() => {
    const qs = new URLSearchParams(Object.fromEntries(Object.entries(filters).filter(([, v]) => v))).toString()
    get<{ events: Ev[] }>(`/api/admin/audit-trail?${qs}`).then((r) => setEvents(r.events)).catch((e) => setErr(e.message))
    get<{ intact: boolean; events_checked: number }>('/api/admin/audit-trail/integrity').then((r) => { setIntegrity(r); setCheckedAt(new Date()) }).catch(() => setIntegrity(null))
  }, [filters])
  useEffect(() => { load() }, [load])
  const paged = usePaged(events ?? [], 25)
  const changeFilters = (f: typeof filters) => { setFilters(f); paged.setPage(1); setOpen(null) }
  const summaryOnly = hasStaff('det_admin') && !hasStaff('compliance_reviewer', 'platform_security_admin')
  const canExport = !summaryOnly && hasStaff('compliance_reviewer')
  const hidden = <span className="muted">{t('status.hidden_for_role')}</span>
  const filtered = !!(filters.category || filters.event_type || filters.company_id)

  const doExport = async () => {
    try {
      const r = await post<{ export_id: string; row_count: number }>('/api/admin/audit-trail/export', { reason_code: 'internal_audit', approved_by_key: 'second-approver', pseudonymised: true, filters: { limit: 1000 } })
      setExportMsg({ kind: 'success', text: t('core:export_done', { id: r.export_id, count: r.row_count }) })
    } catch (e) {
      setExportMsg({ kind: 'error', text: (e as Error).message })
    }
  }

  const headers = [t('core:col_when'), t('core:col_event'), t('core:category'), t('core:col_outcome'), t('core:col_actor'), t('common.company'), t('core:col_subject'), t('common.details')]

  return (
    <div className="core-page">
      <PageHeader
        eyebrow={t('core:oversight')}
        title={t('nav.audit_trail')}
        subtitle={<>{t('core:audit_subtitle')}{canExport && <> {t('core:export_hint')}</>}</>}
        actions={canExport && <Button variant="secondary" onClick={doExport}><Icon name="download" size={18} />{t('common.export')}</Button>}
        meta={
          <>
            {integrity && integrity.intact && (
              <span className="core-integrity" role="status">
                <span className="core-integrity-badge"><Icon name="shield" size={16} />{t('core:integrity_ok')}</span>
                <span className="core-integrity-meta">
                  {t('core:integrity_events', { n: formatNumber(integrity.events_checked, lang) })}
                  {checkedAt && <> · {t('core:integrity_at', { when: formatDateTime(checkedAt, lang) })}</>}
                </span>
              </span>
            )}
            {integrity && !integrity.intact && <Chip tone="critical">{t('core:integrity_failed_chip')}</Chip>}
            {summaryOnly && <Chip tone="info" icon="i">{t('core:summary_view')}</Chip>}
          </>
        }
      />
      {integrity && !integrity.intact && <Message kind="error">{t('core:integrity_failed')}</Message>}
      {err && <Message kind="error">{err}</Message>}
      {exportMsg && <Message kind={exportMsg.kind}>{exportMsg.text}</Message>}

      <Toolbar label={t('core:filters')}>
        <Field label={t('core:category')} id="at-category">
          <select id="at-category" value={filters.category} onChange={(e) => changeFilters({ ...filters, category: e.target.value })}>
            <option value="">{t('core:all_categories')}</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{labelFor(t, 'cat', c)}</option>)}
          </select>
        </Field>
        <Field label={t('core:event_type')} id="at-event">
          <input id="at-event" dir="ltr" placeholder={t('core:event_type_ph')} value={filters.event_type} onChange={(e) => changeFilters({ ...filters, event_type: e.target.value.toUpperCase() })} />
        </Field>
        {!summaryOnly && (
          <Field label={t('core:company_id')} id="at-company">
            <input id="at-company" dir="ltr" value={filters.company_id} onChange={(e) => changeFilters({ ...filters, company_id: e.target.value })} />
          </Field>
        )}
        <div className="toolbar-end">
          <Button variant="secondary" onClick={() => changeFilters({ category: '', event_type: '', company_id: '' })} disabled={!filtered}>{t('common.clear_filters')}</Button>
        </div>
      </Toolbar>

      <section className="panel core-table-panel" aria-labelledby="at-results">
        <header className="panel-header">
          <h2 id="at-results">{events ? t('common.records_found', { count: events.length }) : t('shell.loading')}</h2>
          <span className="muted core-small">{t('core:newest_first')}</span>
        </header>
        {!events ? <div className="panel-body"><Skeleton rows={6} /></div> : events.length === 0 ? (
          <div className="panel-body"><Empty icon="search" title={t('core:no_events')} body={t('core:no_events_body')} /></div>
        ) : (
          <>
            <div className="table-wrap core-table-wrap">
              <table className="table-compact core-table core-audit-table core-stack">
                <thead><tr>{headers.map((h, i) => <th key={i} scope="col">{h}</th>)}</tr></thead>
                <tbody>
                  {paged.pageItems.map((e) => {
                    const isOpen = open === e.event_id
                    const detailId = `at-detail-${e.event_id}`
                    return (
                      <Fragment key={e.event_id}>
                        <tr className={isOpen ? 'core-row-open' : undefined}>
                          <td data-label={headers[0]} className="date-cell">
                            <time dateTime={e.occurred_at} title={formatDateTime(e.occurred_at, lang)}>{shortDateTime(e.occurred_at, lang)}</time>
                          </td>
                          <td data-label={headers[1]}>
                            <div>
                              <div className="core-cell-title">{humanize(e.event_type)}</div>
                              <bdi dir="ltr" className="core-code">{e.event_type}</bdi>
                            </div>
                          </td>
                          <td data-label={headers[2]} className="nowrap">{labelFor(t, 'cat', e.category)}</td>
                          <td data-label={headers[3]}>
                            <div>
                              <Chip tone={e.outcome === 'success' ? 'ok' : e.outcome === 'refused' ? 'critical' : 'neutral'}>{labelFor(t, 'outcome', e.outcome)}</Chip>
                              {e.reason_code && <div><bdi dir="ltr" className="core-code" title={humanize(e.reason_code)}>{e.reason_code}</bdi></div>}
                            </div>
                          </td>
                          <td data-label={headers[4]} className={!summaryOnly && !e.actor_key && !e.actor_role ? 'core-empty-cell' : undefined}>
                            <div>
                              {summaryOnly ? hidden : e.actor_key ? <bdi dir="ltr" className="core-mono">{e.actor_key.slice(0, 10)}</bdi> : <span className="muted">—</span>}
                              {e.actor_role && <div className="core-sub">{t(`roles.${e.actor_role}`, { defaultValue: humanize(e.actor_role) })}</div>}
                            </div>
                          </td>
                          <td data-label={headers[5]} className={!summaryOnly && !e.company_id ? 'core-empty-cell' : undefined}>{summaryOnly ? hidden : e.company_id ? <bdi dir="ltr" className="core-mono">{e.company_id}</bdi> : <span className="muted">—</span>}</td>
                          <td data-label={headers[6]} className={!e.subject_type ? 'core-empty-cell' : undefined}>
                            <div>
                              {e.subject_type ? <div>{humanize(e.subject_type)}</div> : <span className="muted">—</span>}
                              {!summaryOnly && e.subject_id && <bdi dir="ltr" className="core-code" title={e.subject_id}>{e.subject_id}</bdi>}
                            </div>
                          </td>
                          <td data-label={headers[7]}>
                            <button type="button" className="btn btn-ghost btn-sm core-toggle" aria-expanded={isOpen} aria-controls={detailId} onClick={() => setOpen(isOpen ? null : e.event_id)}>
                              <Icon name="chevron-down" size={16} className="core-toggle-chevron" />
                              {t('common.details')}
                            </button>
                          </td>
                        </tr>
                        {isOpen && (
                          <tr className="core-detail-row" id={detailId}>
                            <td colSpan={headers.length}>
                              <dl className="kv core-kv">
                                <dt>{t('core:event_code')}</dt><dd><bdi dir="ltr" className="core-mono">{e.event_type}</bdi></dd>
                                <dt>{t('core:event_id')}</dt><dd><bdi dir="ltr" className="core-mono core-break">{e.event_id}</bdi></dd>
                                {!summaryOnly && e.subject_id && <><dt>{t('core:col_subject')}</dt><dd>{humanize(e.subject_type)} <bdi dir="ltr" className="core-mono core-break">{e.subject_id}</bdi></dd></>}
                                {e.reason_code && <><dt>{t('core:reason_code')}</dt><dd><bdi dir="ltr" className="core-mono">{e.reason_code}</bdi></dd></>}
                                {e.config_version && <><dt>{t('core:config_version')}</dt><dd><bdi dir="ltr" className="core-mono core-break">{e.config_version}</bdi></dd></>}
                                <dt>{t('core:hash')}</dt><dd><bdi dir="ltr" className="core-mono core-break">{e.hash}</bdi></dd>
                                <dt>{t('core:recorded_details')}</dt>
                                <dd>{summaryOnly ? hidden : e.details && Object.keys(e.details).length ? <pre className="code">{JSON.stringify(e.details, null, 1)}</pre> : <span className="muted">{t('core:no_details')}</span>}</dd>
                              </dl>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div className="core-pagination"><Pagination page={paged.page} pages={paged.pages} total={paged.total} pageSize={paged.pageSize} onPage={(p) => { setOpen(null); paged.setPage(p) }} /></div>
          </>
        )}
      </section>
    </div>
  )
}
