import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Field, Message, Panel, Skeleton } from '../../components/ui'
import { ApiError, get, put } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import { type Dashboard, type KpiRecord, type SupTable, SupTableView, srOnly, useFetch, useLang } from './parts'
import Tile from './Tile'

/**
 * SC14 'Pilot KPIs' (E9-S1): filter bar, live tiles (K1-K4, K19), muted 'Coming in later phases' tiles,
 * a breakdown table with allowed dimensions only, CSV export and the minimum-group-size card.
 * Every figure arrives already suppressed by the shared backend engine; the screen never computes figures.
 */
export default function KpisTab() {
  const { t } = useTranslation('kpis')
  const { lang, tx } = useLang()
  const [filters, setFilters] = useState<{ period: string; cohort: string; payment_status: string }>({ period: '', cohort: '', payment_status: '' })
  const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]).toString()
  const { data, error, loading, reload, setData } = useFetch<Dashboard>(`/api/det/kpis${qs ? `?${qs}` : ''}`)
  const [slow, setSlow] = useState(false)
  const [retrying, setRetrying] = useState<string | null>(null)

  useEffect(() => {
    if (!loading) {
      setSlow(false)
      return
    }
    const h = window.setTimeout(() => setSlow(true), (data?.loading_slow_after_seconds ?? 10) * 1000)
    return () => window.clearTimeout(h)
  }, [loading, data?.loading_slow_after_seconds])

  const retryOne = async (id: string) => {
    if (!data) return
    setRetrying(id)
    try {
      const one = await get<{ kpi: KpiRecord }>(`/api/det/kpis/${id}${qs ? `?${qs}` : ''}`)
      setData({ ...data, kpis: data.kpis.map((k) => (k.kpi_id === id ? one.kpi : k)) })
    } catch {
      /* the tile keeps its error state */
    } finally {
      setRetrying(null)
    }
  }

  if (error && !data) {
    if (error instanceof ApiError && error.status === 403) {
      return (
        <Message kind="info">
          {t('no_access')} <a href="/">{t('go_home')}</a>
        </Message>
      )
    }
    return (
      <Message kind="error">
        {t('error_all')} <Button variant="link" onClick={reload}>{t('try_again')}</Button>
      </Message>
    )
  }
  if (!data) {
    return (
      <div aria-busy="true">
        <p style={srOnly} role="status">{t('loading_all')}</p>
        {slow && <p role="status">{t('still_loading')}</p>}
        <div className="grid">{[0, 1, 2, 3, 4].map((i) => <div className="card" key={i}><Skeleton rows={3} /></div>)}</div>
      </div>
    )
  }
  const n = data.suppression.min_group_size
  const live = data.kpis.filter((k) => k.group === 'live')
  const later = data.kpis.filter((k) => k.group === 'later')
  const revenue = live.filter((k) => k.kpi_id === 'K2' || k.kpi_id === 'K3')
  const others = live.filter((k) => k.kpi_id !== 'K2' && k.kpi_id !== 'K3')
  const tile = (k: KpiRecord) => <Tile key={k.kpi_id} k={k} n={n} dataAsOf={data.data_as_of} onRetry={retryOne} retrying={retrying === k.kpi_id} />

  return (
    <div>
      <Message kind="info">{t('banner')}</Message>
      <p>
        <Chip tone={data.demo_data ? 'draft' : 'info'} icon={data.demo_data ? '✎' : 'i'}>{data.demo_data ? t('demo_data') : t('pilot_data')}</Chip>{' '}
        <span className="hint">{t('n_label', { n })} · {t('data_as_of')}: {formatDateTime(data.data_as_of, lang)} · <bdi dir="ltr">{data.data_version}</bdi></span>
      </p>
      {loading && <p style={srOnly} role="status">{t('loading_all')}</p>}

      <FilterBar data={data} value={filters} onChange={setFilters} />

      {data.state === 'blocked' && (
        <Message kind="warning">
          {t('fewer_than', { n })}. {t('blocked')}
        </Message>
      )}
      {data.state === 'empty' && <Message kind="info">{t('empty')}</Message>}

      <section aria-labelledby="kpi-live">
        <h2 id="kpi-live">{t('live_now')}</h2>
        <div className="grid">{others.map(tile)}</div>
        <div className="grid" style={{ marginTop: 16 }}>{revenue.map(tile)}</div>
        <p className="hint"><span aria-hidden="true">ⓘ </span>{t('revenue_note')}</p>
      </section>

      <section aria-labelledby="kpi-later" style={{ marginTop: 24 }}>
        <h2 id="kpi-later">{t('coming_later')}</h2>
        <div className="grid">{later.map(tile)}</div>
      </section>

      {data.state !== 'blocked' && <BreakdownPanel data={data} qs={qs} />}
      {data.can_export && <ExportPanel filters={data.filters} />}
      <SettingsCard canManage={data.can_manage_n} onSaved={reload} />
      <p className="hint">{tx(data.source_label)} · {data.catalogue_version}</p>
    </div>
  )
}

function FilterBar({ data, value, onChange }: { data: Dashboard; value: { period: string; cohort: string; payment_status: string }; onChange: (v: { period: string; cohort: string; payment_status: string }) => void }) {
  const { t } = useTranslation('kpis')
  const [draft, setDraft] = useState({ ...value, period: value.period || data.filters.period })
  return (
    <form
      className="actions"
      role="search"
      aria-label={t('filters')}
      style={{ flexWrap: 'wrap', alignItems: 'flex-end', gap: 12 }}
      onSubmit={(e) => {
        e.preventDefault()
        onChange(draft)
      }}
    >
      <Field label={t('period')} id="kpi-period">
        <select id="kpi-period" value={draft.period} onChange={(e) => setDraft({ ...draft, period: e.target.value })}>
          {data.periods.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </Field>
      <Field label={t('cohort')} id="kpi-cohort">
        <select id="kpi-cohort" value={draft.cohort} onChange={(e) => setDraft({ ...draft, cohort: e.target.value })}>
          <option value="">{t('all')}</option>
          {data.filter_options.cohorts.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </Field>
      <Field label={t('payment_status')} id="kpi-pstatus">
        <select id="kpi-pstatus" value={draft.payment_status} onChange={(e) => setDraft({ ...draft, payment_status: e.target.value })}>
          <option value="">{t('all')}</option>
          {data.filter_options.payment_statuses.map((c) => <option key={c} value={c}>{t(`val.${c}`, { defaultValue: c })}</option>)}
        </select>
      </Field>
      <Button type="submit" variant="secondary">{t('filters')}</Button>
    </form>
  )
}

function BreakdownPanel({ data, qs }: { data: Dashboard; qs: string }) {
  const { t } = useTranslation('kpis')
  const { tx } = useLang()
  const liveKpis = useMemo(() => data.kpis.filter((k) => k.release_state === 'live' && k.dimensions), [data.kpis])
  const [kpi, setKpi] = useState(liveKpis[0]?.kpi_id || 'K1')
  const dims = liveKpis.find((k) => k.kpi_id === kpi)?.dimensions || []
  const [dim, setDim] = useState('')
  const [table, setTable] = useState<SupTable | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const k = liveKpis.find((x) => x.kpi_id === kpi)
  const show = async () => {
    const d = dim || dims[0]
    if (!d) return
    setBusy(true)
    setErr(null)
    try {
      const out = await get<{ breakdown?: SupTable; state: string }>(`/api/det/kpis/${kpi}?dimension=${d}${qs ? `&${qs}` : ''}`)
      setTable(out.breakdown || null)
      if (out.state === 'blocked') setErr(t('blocked'))
    } catch (e) {
      setErr(e instanceof ApiError && e.code === 'DIMENSION_NOT_ALLOWED' ? t('fixed_periods') : t('error_all'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel title={t('breakdown')} id="kpi-breakdown">
      <p className="hint">{t('fixed_periods')}</p>
      <div className="actions" style={{ flexWrap: 'wrap', alignItems: 'flex-end', gap: 12 }}>
        <Field label={t('choose_kpi')} id="bd-kpi">
          <select id="bd-kpi" value={kpi} onChange={(e) => { setKpi(e.target.value); setDim(''); setTable(null) }}>
            {liveKpis.map((x) => <option key={x.kpi_id} value={x.kpi_id}>{x.kpi_id} · {tx(x.name)}</option>)}
          </select>
        </Field>
        <Field label={t('choose_dimension')} id="bd-dim">
          <select id="bd-dim" value={dim || dims[0] || ''} onChange={(e) => { setDim(e.target.value); setTable(null) }}>
            {dims.map((d) => <option key={d} value={d}>{t(`dim.${d}`)}</option>)}
          </select>
        </Field>
        <Button variant="secondary" onClick={show} disabled={busy}>{t('show_breakdown')}</Button>
      </div>
      {busy && <Skeleton rows={3} />}
      {err && <Message kind="warning">{err}</Message>}
      {table && k && <SupTableView table={table} n={data.suppression.min_group_size} caption={`${t('breakdown_for', { name: tx(k.name) })} ${t(`dim.${dim || dims[0]}`)}`} />}
    </Panel>
  )
}

function ExportPanel({ filters }: { filters: Dashboard['filters'] }) {
  const { t } = useTranslation('kpis')
  const { lang } = useLang()
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>('idle')
  const run = async () => {
    setState('busy')
    try {
      const res = await fetch('/api/det/kpis/export', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...filters, language: lang }) })
      if (!res.ok) throw new Error(String(res.status))
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `det-pilot-kpis-${filters.period}-${res.headers.get('X-Export-Id') || 'export'}.csv`
      a.click()
      URL.revokeObjectURL(a.href)
      setState('done')
    } catch {
      setState('error')
    }
  }
  return (
    <div className="actions" style={{ marginTop: 16, flexWrap: 'wrap' }}>
      <Button variant="secondary" onClick={run} disabled={state === 'busy'}>{state === 'busy' ? t('exporting') : t('export')}</Button>
      {state === 'done' && <span role="status" className="hint">{t('export_done')}</span>}
      {state === 'error' && <span role="alert" className="hint">{t('export_failed')}</span>}
    </div>
  )
}

interface SettingsView { min_group_size: number; min: number; max: number; can_manage: boolean; history: { version: number; value: number; changed_by: string; effective_from: string | null }[] }

function SettingsCard({ canManage, onSaved }: { canManage: boolean; onSaved: () => void }) {
  const { t } = useTranslation('kpis')
  const { lang } = useLang()
  const { data, reload } = useFetch<SettingsView>('/api/det/settings')
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')
  const [consulted, setConsulted] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  if (!data) return null
  const save = async () => {
    const v = Number(value)
    if (!Number.isInteger(v) || v < data.min || v > data.max) return setMsg({ kind: 'error', text: t('settings_range') })
    if (!reason.trim()) return setMsg({ kind: 'error', text: t('settings_reason_required') })
    try {
      await put('/api/det/settings/min-group-size', { value: v, reason, consulted_compliance_lead: consulted })
      setMsg({ kind: 'success', text: t('settings_saved') })
      setValue('')
      setReason('')
      reload()
      onSaved()
    } catch (e) {
      setMsg({ kind: 'error', text: e instanceof ApiError && e.code.startsWith('MIN_GROUP_SIZE') ? t('settings_range') : t('error_all') })
    }
  }
  return (
    <Panel title={t('settings_title')} id="kpi-settings">
      <p>{t('n_label', { n: data.min_group_size })}</p>
      <p className="hint">{t('settings_intro')} {t('settings_owner')}</p>
      {canManage ? (
        <div>
          <Field label={t('settings_value')} id="n-value">
            <input id="n-value" type="number" inputMode="numeric" min={data.min} max={data.max} step={1} value={value} onChange={(e) => setValue(e.target.value)} />
          </Field>
          <Field label={t('settings_reason')} id="n-reason">
            <input id="n-reason" type="text" maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', minHeight: 44 }}>
            <input type="checkbox" checked={consulted} onChange={(e) => setConsulted(e.target.checked)} /> {t('settings_consulted')}
          </label>
          <Button onClick={save}>{t('settings_save')}</Button>
        </div>
      ) : (
        <p className="hint"><span aria-hidden="true">ⓘ </span>{t('settings_readonly')}</p>
      )}
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      {data.history.length > 0 && (
        <details>
          <summary style={{ minHeight: 44, display: 'flex', alignItems: 'center', cursor: 'pointer' }}>{t('settings_history')}</summary>
          <ul className="timeline">
            {data.history.map((h) => (
              <li key={h.version}><bdi dir="ltr">v{h.version}</bdi> · N = <bdi dir="ltr">{h.value}</bdi> · {formatDate(h.effective_from, lang)}</li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  )
}
