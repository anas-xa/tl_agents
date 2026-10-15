import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Chip, Empty, Field, Ident, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, get } from '../../lib/api'

interface Row { event_id: string; time: string; time_label: string; kind: number; action: string; actor: string; actor_key: string | null; company: string; object_ref: string | null; outcome: 'done' | 'refused' | 'quarantined'; outcome_label: string; reason_code: string | null }
interface Page { rows: Row[]; page: number; page_size: number; total: number; own_only: boolean; retention_months: number }

/** SC15 owner/delegate activity list: plain-language rows, newest first, 50 per page, filters, PDF export stub. */
export default function Activity() {
  const { t, i18n } = useTranslation('activity')
  const { companyId } = useAuth()
  const [data, setData] = useState<Page | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({ kind: '', outcome: '', since: '', until: '', actor: '' })
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const load = useCallback(async () => {
    if (!companyId) return
    const q = new URLSearchParams({ page: String(page), lang })
    if (filters.kind) q.set('kind', filters.kind)
    if (filters.outcome) q.set('outcome', filters.outcome)
    if (filters.since) q.set('since', `${filters.since}T00:00:00`)
    if (filters.until) q.set('until', `${filters.until}T23:59:59`)
    if (filters.actor) q.set('actor', filters.actor)
    try {
      setData(await get<Page>(`/api/companies/${companyId}/activity?${q}`))
      setErr(null)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message)
    }
  }, [companyId, page, filters, lang])
  useEffect(() => {
    load()
  }, [load])
  if (!companyId) return null
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  const actors = data ? [...new Map(data.rows.filter((r) => r.actor_key).map((r) => [r.actor_key as string, r.actor])).entries()] : []
  const exportPdf = async () => {
    try {
      const out = await get<{ pages: { lang: string; html: string }[] }>(`/api/companies/${companyId}/activity/export?lang=${lang}`)
      const html = `<!doctype html><html><head><meta charset="utf-8"><title>${t('title')}</title><style>table{border-collapse:collapse;width:100%}td{border:1px solid #ccc;padding:6px;vertical-align:top}section{page-break-after:always;font-family:system-ui}</style></head><body>${out.pages.map((p) => p.html).join('')}</body></html>`
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
      window.open(url, '_blank', 'noopener')
      setMsg(t('export_ready'))
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  const tone = (o: Row['outcome']) => (o === 'done' ? 'ok' : o === 'refused' ? 'critical' : 'attention')
  return (
    <div>
      <h1>{t('title')}</h1>
      <p className="helper">{t('intro')}</p>
      {data?.own_only && <Message kind="info">{t('own_only')}</Message>}
      {err && <Message kind="error">{err}</Message>}
      {msg && <Message kind="success">{msg}</Message>}
      <Panel
        title={t('title')}
        id="activity"
        actions={<Button variant="secondary" onClick={exportPdf} title={t('export_hint')}>{t('export')}</Button>}
      >
        <form className="grid" onSubmit={(e) => { e.preventDefault(); setPage(1); load() }} role="search" aria-label={t('common.filter', { ns: 'translation' })}>
          <Field label={t('filter_type')} id="f-kind">
            <select id="f-kind" value={filters.kind} onChange={(e) => { setPage(1); setFilters({ ...filters, kind: e.target.value }) }}>
              <option value="">{t('all')}</option>
              {Array.from({ length: 14 }, (_, i) => i + 1).map((k) => <option key={k} value={k}>{t(`k${k}`)}</option>)}
            </select>
          </Field>
          <Field label={t('filter_outcome')} id="f-outcome">
            <select id="f-outcome" value={filters.outcome} onChange={(e) => { setPage(1); setFilters({ ...filters, outcome: e.target.value }) }}>
              <option value="">{t('all')}</option>
              {(['done', 'refused', 'quarantined'] as const).map((o) => <option key={o} value={o}>{t(`outcome_${o}`)}</option>)}
            </select>
          </Field>
          {!data?.own_only && (
            <Field label={t('filter_actor')} id="f-actor">
              <select id="f-actor" value={filters.actor} onChange={(e) => { setPage(1); setFilters({ ...filters, actor: e.target.value }) }}>
                <option value="">{t('all')}</option>
                {actors.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </Field>
          )}
          <Field label={t('filter_from')} id="f-since"><input id="f-since" type="date" dir="ltr" value={filters.since} onChange={(e) => { setPage(1); setFilters({ ...filters, since: e.target.value }) }} /></Field>
          <Field label={t('filter_to')} id="f-until"><input id="f-until" type="date" dir="ltr" value={filters.until} onChange={(e) => { setPage(1); setFilters({ ...filters, until: e.target.value }) }} /></Field>
        </form>
        {!data ? <Skeleton rows={5} /> : data.rows.length === 0 ? <Empty title={t('no_results')} /> : (
          <Table headers={[t('col_time'), t('col_actor'), t('col_action'), t('col_company'), t('col_object'), t('col_outcome')]}>
            {data.rows.map((r) => (
              <tr key={r.event_id}>
                <td><bdi dir="ltr">{r.time_label}</bdi></td>
                <td><span aria-hidden="true">{r.actor.includes('AI') || r.actor.includes('الذكاء') ? '✎' : '👤'}</span> <bdi>{r.actor}</bdi></td>
                <td>{r.action}</td>
                <td><bdi>{r.company}</bdi></td>
                <td>{r.object_ref ? <Ident>{r.object_ref}</Ident> : '—'}</td>
                <td><Chip tone={tone(r.outcome)}>{r.outcome_label}</Chip>{r.reason_code && <div className="helper">{t('reason')}: <Ident>{r.reason_code}</Ident></div>}</td>
              </tr>
            ))}
          </Table>
        )}
        {data && (
          <div className="actions" aria-live="polite">
            <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>{t('prev')}</Button>
            <span>{t('page', { p: page, n: pages })}</span>
            <Button variant="secondary" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>{t('next')}</Button>
            <span className="muted">{t('retention', { n: data.retention_months })}</span>
          </div>
        )}
      </Panel>
    </div>
  )
}
