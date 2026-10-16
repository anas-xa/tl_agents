import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Disclosure, Message, Panel, Skeleton } from '../../components/ui'
import { formatDate, formatDateTime } from '../../lib/format'
import { useBi, useFetch, type Bi } from './lib'

interface Gate { gate_id: string; description: Bi; panel_status: string; panel_label: Bi; gate_type: string }
interface Card { id: string; name: Bi; status: string; status_label: Bi; entry_gate?: Bi; manual_fallback?: Bi | null; demo_outcome?: Bi | null; gates: Gate[]; gated_items?: { title: string; label: Bi; clickable: boolean }[]; waiting_for?: Bi | null; until_then?: Bi | null; last_changed_at?: string }
interface Feature { key: string; available: boolean; note: Bi | null; button: Bi | null; route: string | null; manual_label: Bi | null }
interface WhatsLive { panel_title: Bi; published: boolean; empty_message: Bi | null; increments: Card[]; features: Feature[]; phase_strip: { phase: number; label: Bi; marker: string }[] }

const INC_ICON: Record<string, string> = { not_started: '○', in_build: '🔧', manual_path_live: '✋', live: '✓', demo_done: '⚑', not_assigned: '—', status_unavailable: '◌' }
const GATE_ICON: Record<string, string> = { not_met: '🔒', in_progress: '⌛', met: '✓', not_needed_in_pilot: '⊖' }

/** SC3 'What is live in your pilot' panel (E1-S7) with owner-side availability notes and manual-route buttons (E1-S8). */
export default function WhatsLivePanel() {
  const { t, i18n } = useTranslation('det')
  const { tx } = useBi()
  const { companyId } = useAuth()
  const nav = useNavigate()
  const { data, error, loading, loadedAt, reload } = useFetch<WhatsLive>(companyId ? `/api/companies/${companyId}/whats-live` : null, [companyId])
  const [openId, setOpenId] = useState<string | null>(null)
  if (loading && !data) return <Panel title={t('wl_title')} id="whats-live"><p aria-busy="true" className="visually-hidden">{t('wl_loading')}</p><Skeleton rows={3} /></Panel>
  if (error && !data) return <Panel title={t('wl_title')} id="whats-live"><Message kind="error">{t('phase_error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message></Panel>
  if (!data) return null
  const tone = (s: string) => (s === 'live' || s === 'demo_done' ? 'ok' : s === 'manual_path_live' ? 'info' : s === 'in_build' ? 'attention' : 'neutral')
  const routes = data.features.filter((f) => f.note || f.manual_label || (f.button && f.route))
  return (
    <Panel title={tx(data.panel_title)} id="whats-live">
      {error && loadedAt && <Message kind="warning">{t('gates_error')} {t('last_known', { date: formatDateTime(loadedAt, i18n.language) })}</Message>}
      {!data.published && data.empty_message && <Message kind="info">{tx(data.empty_message)}</Message>}
      <div className="wl-grid">
        <div className="wl-main">
          <ol className="dash-status-list wl-increments">
            {data.increments.map((c) => {
              const open = openId === c.id
              return (
                <li key={c.id}>
                  <h3 className="dash-status-name wl-inc-name"><bdi dir="ltr" className="wl-inc-id">{c.id}</bdi> {tx(c.name)}</h3>
                  <span className="dash-status-end">
                    <Chip tone={tone(c.status)} icon={INC_ICON[c.status]}>{tx(c.status_label)}</Chip>
                    {c.status !== 'not_assigned' && (
                      <Button variant="link" className="wl-toggle" aria-expanded={open} aria-controls={`wl-${c.id}`} onClick={() => setOpenId(open ? null : c.id)}>
                        {t('wl_expand')} <span aria-hidden="true">{open ? '▴' : '▾'}</span>
                      </Button>
                    )}
                  </span>
                  {c.status !== 'not_assigned' && open && (
                    <div id={`wl-${c.id}`} className="wl-detail">
                      {c.gates.filter((g) => g.gate_type === 'entry_gate').map((g) => (
                        <p key={g.gate_id}>{t('entry_gate')}: {tx(g.description)} <Chip tone={g.panel_status === 'met' ? 'ok' : g.panel_status === 'in_progress' ? 'attention' : 'neutral'} icon={GATE_ICON[g.panel_status] ?? '◌'}>{tx(g.panel_label)}</Chip></p>
                      ))}
                      {c.waiting_for && <p>{tx(c.waiting_for)}</p>}
                      {c.until_then && <p>{tx(c.until_then)}</p>}
                      {c.manual_fallback && <p>{t('fallback')}: {tx(c.manual_fallback)}</p>}
                      {c.demo_outcome && <p>{t('demo_outcome')}: {tx(c.demo_outcome)}</p>}
                      {c.gated_items?.map((g) => <p key={g.title}><span aria-hidden="true">🔒 </span><strong>{g.title}</strong> <span aria-disabled="true">{tx(g.label)}</span></p>)}
                      {c.last_changed_at && <p className="hint">{t('status_changed', { date: formatDate(c.last_changed_at, i18n.language) })}</p>}
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
          {routes.length > 0 && (
            <Disclosure summary={`${t('wl_manual_route')} (${routes.length})`}>
              <ul className="dash-status-list">
                {routes.map((f) => (
                  <li key={f.key}>
                    <span className="dash-status-name">
                      {f.note && <span>{tx(f.note)} </span>}
                      {f.manual_label && <Chip tone="draft">{tx(f.manual_label)}</Chip>}
                    </span>
                    {f.button && f.route && <Button variant="secondary" onClick={() => nav(f.route!)}>{tx(f.button)}</Button>}
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}
        </div>
        <div className="wl-phases">
          <h3>{t('dashboard:pilot_phases')}</h3>
          <ol className="wl-phase-list">
            {data.phase_strip.map((p) => {
              const cur = p.marker === 'Current'
              const done = p.marker === 'Done'
              return (
                <li key={p.phase} className={cur ? 'wl-phase-current' : done ? 'wl-phase-done' : ''}>
                  <span className="wl-phase-mark" aria-hidden="true">{done ? '✓' : cur ? '●' : '○'}</span>
                  <span className="wl-phase-text">{tx(p.label)} <span className="wl-phase-state">· {cur ? t('current') : done ? t('done') : t('later')}</span></span>
                </li>
              )
            })}
          </ol>
        </div>
      </div>
    </Panel>
  )
}
