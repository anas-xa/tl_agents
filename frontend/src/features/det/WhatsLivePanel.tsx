import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Message, Panel, Skeleton } from '../../components/ui'
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
  if (loading && !data) return <Panel title={t('wl_title')}><p aria-busy="true">{t('wl_loading')}</p><Skeleton rows={4} /></Panel>
  if (error && !data) return <Panel title={t('wl_title')}><Message kind="error">{t('phase_error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message></Panel>
  if (!data) return null
  const tone = (s: string) => (s === 'live' || s === 'demo_done' ? 'ok' : s === 'manual_path_live' ? 'info' : s === 'in_build' ? 'attention' : 'neutral')
  return (
    <Panel title={tx(data.panel_title)} id="whats-live">
      {error && loadedAt && <Message kind="warning">{t('gates_error')} {t('last_known', { date: formatDateTime(loadedAt, i18n.language) })}</Message>}
      {!data.published && data.empty_message && <Message kind="info">{tx(data.empty_message)}</Message>}
      <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {data.increments.map((c) => {
          const open = openId === c.id
          return (
            <li key={c.id} style={{ borderInlineStart: '3px solid var(--border)', paddingInlineStart: 12, marginBottom: 12 }}>
              <h3 style={{ margin: '4px 0' }}><bdi dir="ltr">{c.id}</bdi> {tx(c.name)}: <Chip tone={tone(c.status)} icon={INC_ICON[c.status]}>{tx(c.status_label)}</Chip></h3>
              {c.status !== 'not_assigned' && (
                <>
                  <Button variant="link" aria-expanded={open} aria-controls={`wl-${c.id}`} onClick={() => setOpenId(open ? null : c.id)}>{t('wl_expand')} {open ? '▴' : '▾'}</Button>
                  {open && (
                    <div id={`wl-${c.id}`}>
                      {c.gates.filter((g) => g.gate_type === 'entry_gate').map((g) => (
                        <p key={g.gate_id}>{t('entry_gate')}: {tx(g.description)} <Chip tone={g.panel_status === 'met' ? 'ok' : g.panel_status === 'in_progress' ? 'attention' : 'neutral'} icon={GATE_ICON[g.panel_status] ?? '◌'}>{tx(g.panel_label)}</Chip></p>
                      ))}
                      {c.waiting_for && <p>{tx(c.waiting_for)}</p>}
                      {c.until_then && <p>{tx(c.until_then)}</p>}
                      {c.manual_fallback && <p>{t('fallback')}: {tx(c.manual_fallback)}</p>}
                      {c.demo_outcome && <p>{t('demo_outcome')}: {tx(c.demo_outcome)}</p>}
                      {c.gated_items?.map((g) => <p key={g.title}><Chip tone="neutral" icon="🔒">{g.title}</Chip> <span aria-disabled="true">{tx(g.label)}</span></p>)}
                      {c.last_changed_at && <p className="hint">{t('status_changed', { date: formatDate(c.last_changed_at, i18n.language) })}</p>}
                    </div>
                  )}
                </>
              )}
            </li>
          )
        })}
      </ol>
      <h3>{t('wl_manual_route')}</h3>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {data.features.map((f) => (
          <li key={f.key} style={{ marginBottom: 8 }}>
            {f.note && <span>{tx(f.note)} </span>}
            {f.manual_label && <Chip tone="draft">{tx(f.manual_label)}</Chip>}{' '}
            {f.button && f.route && <Button variant="secondary" onClick={() => nav(f.route!)}>{tx(f.button)}</Button>}
          </li>
        ))}
      </ul>
      <ol style={{ display: 'flex', flexWrap: 'wrap', gap: 8, listStyle: 'none', padding: 0 }}>
        {data.phase_strip.map((p) => (
          <li key={p.phase}><Chip tone={p.marker === 'Current' ? 'info' : p.marker === 'Done' ? 'ok' : 'neutral'}>{tx(p.label)} · {p.marker === 'Current' ? t('current') : p.marker === 'Done' ? t('done') : t('later')}</Chip></li>
        ))}
      </ol>
    </Panel>
  )
}
