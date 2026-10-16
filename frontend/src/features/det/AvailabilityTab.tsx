import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip, Message, Panel, Skeleton, Table } from '../../components/ui'
import { formatDateTime, formatPercent } from '../../lib/format'
import { useFetch } from './lib'

interface Stats { measured_minutes: number; available_minutes: number; down_minutes: number; no_data_minutes: number; unmeasured_minutes: number; total_minutes: number; availability_pct: number | null; incomplete_measurement: boolean }
interface Win { window_id: string; window_code: string; name_en: string; name_ar: string; start_local: string | null; end_local: string | null; config_version: string; partial: boolean; partial_label: string | null; covered_minutes: number; full_minutes: number; languages: Record<'ar' | 'en', Stats>; placeholder: boolean }
interface K26 { state: 'no_window' | 'measured' | 'incomplete'; value: number | null; message: string | null; target_pct: number; next_window: { name_en: string; name_ar: string; start_local: string | null } | null; config_version: string; languages: Record<string, Stats>; combined: Stats | null; windows: Win[] }
interface Minute { minute_ts: string; minute_local: string; ar: { status: string; failed: string[] }; en: { status: string; failed: string[] }; peak_windows: string[] }
interface Avail { period: string; k26: K26; tile: { state: string; message: string | null; checks: Record<string, { result: string; latency_ms: number | null }>; last_checked: string | null }; timeline: Minute[]; windows: { window_id: string; window_code: string; name_en: string; name_ar: string; start_local: string | null; end_local: string | null; config_version: string }[] }

const PATTERN: Record<string, string> = { up: 'var(--ok)', down: 'var(--critical)', no_data: 'repeating-linear-gradient(45deg, var(--muted) 0 2px, transparent 2px 4px)', unmeasured: 'var(--border)' }

/** SC14 'Operations' tile (E1-S9): K26 per window per language, minute timeline, probe status. No company data. */
export default function AvailabilityTab() {
  const { t, i18n } = useTranslation('det')
  const ar = i18n.language.startsWith('ar')
  const [period, setPeriod] = useState('day')
  const [windowId, setWindowId] = useState('')
  const [view, setView] = useState<'timeline' | 'table'>('timeline')
  const q = period === 'window' && windowId ? `period=window&window_id=${windowId}` : `period=${period}`
  const { data, error, loading, reload } = useFetch<Avail>(`/api/det/availability?${q}`)
  if (loading && !data) return <div aria-busy="true"><p>{t('loading_availability', { period: t(`period_${period}`) })}</p><Skeleton rows={4} /></div>
  if (error && !data) return <Message kind="error">{t('availability_error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message>
  if (!data) return null
  const k = data.k26
  const name = (w: { name_en: string; name_ar: string }) => (ar ? w.name_ar : w.name_en)
  return (
    <div>
      <div className="toolbar det-toolbar" role="group" aria-label={t('period')}>
        <div className="det-seg">
        {(['day', 'week', 'month', 'window'] as const).map((p) => (
          <button type="button" key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>{t(`period_${p}`)}</button>
        ))}
        </div>
        {period === 'window' && (
          <select aria-label={t('period_window')} value={windowId} onChange={(e) => setWindowId(e.target.value)}>
            <option value="">—</option>
            {data.windows.map((w) => <option key={w.window_id} value={w.window_id}>{name(w)} ({w.start_local} – {w.end_local})</option>)}
          </select>
        )}
      </div>
      <div className="det-card-grid det-card-grid-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))' }}>
        <div className="card det-status-card">
          <h3><Icon name="activity" size={18} />{t('k26_title')}</h3>
          {data.tile.state === 'no_probes_yet' ? (
            <p>{t('no_probes')}</p>
          ) : k.state === 'no_window' ? (
            <>
              <p><Chip tone="neutral" icon="—">{t('no_window')}</Chip></p>
              {k.next_window && <p>{t('next_window')}: {name(k.next_window)} · {k.next_window.start_local}</p>}
            </>
          ) : (
            <>
              <p className="det-kpi-value"><bdi dir="ltr">{k.value === null ? '—' : formatPercent(k.value, i18n.language, 2)}</bdi></p>
              {k.state === 'incomplete' && <p><Chip tone="attention" icon="◔">{t('incomplete')}</Chip></p>}
              <p className="det-kpi-target">{t('target', { pct: k.target_pct })} · {t('versions_note')} · <bdi dir="ltr">{k.config_version}</bdi></p>
            </>
          )}
        </div>
        <div className="card det-status-card">
          <h3><Icon name="check" size={18} />{t('probe_status')}</h3>
          {data.tile.state === 'no_probes_yet' ? <p>{t('no_probes')}</p> : (
            <>
              <div className="det-switches">
              {Object.entries(data.tile.checks).map(([key, c]) => (
                <Chip key={key} tone={c.result === 'up' ? 'ok' : c.result === 'down' ? 'critical' : 'neutral'} icon={c.result === 'up' ? '✓' : c.result === 'down' ? '✕' : '?'}>{key.replace('_', '-')}: {t(c.result as 'up' | 'down' | 'no_data')}</Chip>
              ))}
              </div>
              {data.tile.last_checked && <p className="hint">{t('last_checked', { time: formatDateTime(data.tile.last_checked, i18n.language) })}</p>}
            </>
          )}
          <p className="det-kpi-target">{t('identity_note')}</p>
        </div>
      </div>
      {k.windows.length > 0 && (
        <Panel title={t('period_window')} className="det-panel-flush">
          <div className="table-compact det-table">
          <Table headers={[t('col_window'), t('col_minutes'), 'AR ' + t('col_availability'), 'EN ' + t('col_availability'), t('col_down'), t('col_no_data'), t('col_unmeasured'), t('col_version_short')]}>
            {k.windows.map((w) => (
              <tr key={w.window_id}>
                <td>{name(w)} {w.partial && <Chip tone="attention">{t('partial_window')}</Chip>} {w.placeholder && <Chip tone="draft">{t('demo_data')}</Chip>}<div className="hint"><bdi dir="ltr">{w.start_local}</bdi> – <bdi dir="ltr">{w.end_local}</bdi></div></td>
                <td>{w.partial ? `${w.covered_minutes} / ${w.full_minutes}` : w.full_minutes}</td>
                <td>{w.languages.ar.availability_pct === null ? '—' : formatPercent(w.languages.ar.availability_pct, i18n.language, 2)}{w.languages.ar.incomplete_measurement && <> <Chip tone="attention">{t('incomplete')}</Chip></>}</td>
                <td>{w.languages.en.availability_pct === null ? '—' : formatPercent(w.languages.en.availability_pct, i18n.language, 2)}</td>
                <td>{w.languages.ar.down_minutes + w.languages.en.down_minutes}</td>
                <td>{w.languages.ar.no_data_minutes + w.languages.en.no_data_minutes}</td>
                <td>{w.languages.ar.unmeasured_minutes + w.languages.en.unmeasured_minutes}</td>
                <td><bdi dir="ltr">{w.config_version}</bdi></td>
              </tr>
            ))}
          </Table>
          </div>
        </Panel>
      )}
      <Panel title={t('timeline')} actions={<Button variant="secondary" className="det-rowbtn" onClick={() => setView(view === 'timeline' ? 'table' : 'timeline')}>{view === 'timeline' ? t('table_view') : t('timeline_view')}</Button>}>
        <p className="det-note">{t('down_legend')} · {t('no_data_legend')}</p>
        <div className="det-legend" aria-hidden="true">
          {(['up', 'down', 'no_data', 'unmeasured'] as const).map((s) => <span key={s}><span className="det-swatch" style={{ background: PATTERN[s] }} />{t(s)}</span>)}
        </div>
        {view === 'timeline' ? (
          <div className="det-timeline" role="img" aria-label={t('timeline')}>
            {data.timeline.slice(-720).map((m) => (
              <span key={m.minute_ts} title={`${m.minute_local} · AR ${t(m.ar.status as 'up')}${m.ar.failed.length ? ` (${m.ar.failed.join(', ')})` : ''} · EN ${t(m.en.status as 'up')}${m.en.failed.length ? ` (${m.en.failed.join(', ')})` : ''}${m.peak_windows.length ? ` · ${m.peak_windows.join(', ')}` : ''}`} style={{ width: 4, height: 18, background: PATTERN[m.ar.status === 'down' || m.en.status === 'down' ? 'down' : m.ar.status === 'up' && m.en.status === 'up' ? 'up' : m.ar.status === 'no_data' || m.en.status === 'no_data' ? 'no_data' : 'unmeasured'], outline: m.peak_windows.length ? '1px solid var(--accent)' : undefined }} />
            ))}
          </div>
        ) : (
          <Table headers={[t('col_date'), 'AR', 'EN', t('col_window')]}>
            {data.timeline.filter((m) => m.ar.status !== 'up' || m.en.status !== 'up').slice(-200).map((m) => (
              <tr key={m.minute_ts}>
                <td><bdi dir="ltr">{m.minute_local}</bdi></td>
                <td>{t(m.ar.status as 'up')} {m.ar.failed.join(', ')}</td>
                <td>{t(m.en.status as 'up')} {m.en.failed.join(', ')}</td>
                <td>{m.peak_windows.join(', ')}</td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  )
}
