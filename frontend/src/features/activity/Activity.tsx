import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Empty, Field, Ident, Message, PageHeader, Pagination, Skeleton } from '../../components/ui'
import { digits, formatDate } from '../../lib/format'
import { ApiError, get } from '../../lib/api'
import './activity.css'

interface Row { event_id: string; time: string; time_label: string; kind: number; action: string; actor: string; actor_key: string | null; company: string; object_ref: string | null; outcome: 'done' | 'refused' | 'quarantined'; outcome_label: string; reason_code: string | null }
interface Page { rows: Row[]; page: number; page_size: number; total: number; own_only: boolean; retention_months: number }

/** SC15 owner/delegate activity list: plain-language rows, newest first, 50 per page, filters, PDF export stub. */
export default function Activity() {
  const { t, i18n } = useTranslation('activity')
  const { companyId } = useAuth()
  const [data, setData] = useState<Page | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [vpage, setVpage] = useState(1)
  // The API pages by 50; the list shows 25 rows at a time over the same pages (same calls, shorter screen).
  const serverSize = data?.page_size ?? 50
  const view = serverSize % 25 === 0 ? 25 : serverSize
  const page = Math.floor(((vpage - 1) * view) / serverSize) + 1
  const offset = ((vpage - 1) * view) % serverSize
  const setPage = (n: number | ((p: number) => number)) => setVpage((v) => (typeof n === 'function' ? n(v) : n))
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
  const rows = data ? data.rows.slice(offset, offset + view) : []
  const groups: { day: string; rows: Row[] }[] = []
  for (const r of rows) {
    const day = dubaiDay(r.time)
    const g = groups[groups.length - 1]
    if (g && g.day === day) g.rows.push(r)
    else groups.push({ day, rows: [r] })
  }
  const setFilter = (k: keyof typeof filters, v: string) => { setPage(1); setFilters({ ...filters, [k]: v }) }
  return (
    <div className="act-page">
      <PageHeader
        title={t('title')}
        subtitle={t('intro')}
        actions={<Button variant="secondary" onClick={exportPdf} title={t('export_hint')}><Icon name="download" size={18} />{t('export')}</Button>}
      />
      {data?.own_only && <Message kind="info">{t('own_only')}</Message>}
      {err && <Message kind="error">{err}</Message>}
      {msg && <Message kind="success">{msg}</Message>}
      <form className="toolbar act-toolbar" onSubmit={(e) => { e.preventDefault(); setPage(1); load() }} role="search" aria-label={t('common.filter', { ns: 'translation' })}>
        <Field label={t('filter_type')} id="f-kind">
          <select id="f-kind" value={filters.kind} onChange={(e) => setFilter('kind', e.target.value)}>
            <option value="">{t('all')}</option>
            {Array.from({ length: 14 }, (_, i) => i + 1).map((k) => <option key={k} value={k}>{t(`k${k}`)}</option>)}
          </select>
        </Field>
        <Field label={t('filter_outcome')} id="f-outcome">
          <select id="f-outcome" value={filters.outcome} onChange={(e) => setFilter('outcome', e.target.value)}>
            <option value="">{t('all')}</option>
            {(['done', 'refused', 'quarantined'] as const).map((o) => <option key={o} value={o}>{t(`outcome_${o}`)}</option>)}
          </select>
        </Field>
        {!data?.own_only && (
          <Field label={t('filter_actor')} id="f-actor">
            <select id="f-actor" value={filters.actor} onChange={(e) => setFilter('actor', e.target.value)}>
              <option value="">{t('all')}</option>
              {actors.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </Field>
        )}
        <Field label={t('filter_from')} id="f-since"><input id="f-since" type="date" dir="ltr" value={filters.since} onChange={(e) => setFilter('since', e.target.value)} /></Field>
        <Field label={t('filter_to')} id="f-until"><input id="f-until" type="date" dir="ltr" value={filters.until} onChange={(e) => setFilter('until', e.target.value)} /></Field>
      </form>
      <section className="panel act-panel" aria-labelledby="activity-list-title" id="activity">
        <header className="panel-header">
          <h2 id="activity-list-title">{t('title')}</h2>
          <span className="act-tz"><Icon name="clock" size={14} />{t('times_dubai')}</span>
        </header>
        <div className="panel-body">
          {!data ? <Skeleton rows={5} /> : data.rows.length === 0 ? <Empty icon="activity" title={t('no_results')} /> : (
            groups.map((g) => (
              <div key={g.day} className="act-day">
                <h3 className="act-day-title">{formatDate(g.day, lang)}</h3>
                <ol className="act-list">
                  {g.rows.map((r) => {
                    const ai = r.actor.includes('AI') || r.actor.includes('الذكاء')
                    return (
                      <li key={r.event_id} className="act-row">
                        <time className="act-time" dateTime={r.time} title={r.time_label}><bdi dir="ltr">{dubaiTime(r.time, lang)}</bdi></time>
                        <span className={`act-icon ${ai ? 'is-ai' : ''}`} aria-hidden="true"><Icon name={ai ? 'sparkle' : 'user'} size={16} /></span>
                        <div className="act-main">
                          <span className="act-what">{r.action}</span>
                          <span className="act-meta">
                            <bdi>{r.actor}</bdi>
                            <span aria-hidden="true">·</span>
                            <span className="visually-hidden">{t('col_company')}: </span><bdi>{r.company}</bdi>
                            {r.object_ref && <><span aria-hidden="true">·</span><span className="visually-hidden">{t('col_object')}: </span><span className="act-ref"><Ident>{r.object_ref}</Ident></span></>}
                          </span>
                          {r.reason_code && <span className="act-meta">{t('reason')}: <Ident>{r.reason_code}</Ident></span>}
                        </div>
                        <span className="act-outcome"><span className="visually-hidden">{t('col_outcome')}: </span><Chip tone={tone(r.outcome)}>{r.outcome_label}</Chip></span>
                      </li>
                    )
                  })}
                </ol>
              </div>
            ))
          )}
          {data && <Pagination page={vpage} pages={Math.max(1, Math.ceil(data.total / view))} total={data.total} pageSize={view} onPage={setPage} />}
          {data && <p className="act-retention">{t('retention', { n: data.retention_months })}</p>}
        </div>
      </section>
    </div>
  )
}

/** Calendar day (YYYY-MM-DD) of an instant in Dubai time, for grouping. */
function dubaiDay(value: string): string {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Dubai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
  } catch {
    return value.slice(0, 10)
  }
}

function dubaiTime(value: string, lang: string): string {
  try {
    return digits(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Dubai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)), lang)
  } catch {
    return value.slice(11, 16)
  }
}
