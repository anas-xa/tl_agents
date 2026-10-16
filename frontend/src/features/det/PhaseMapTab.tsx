import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Disclosure, Field, Message, Panel, Skeleton, Table } from '../../components/ui'
import { post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import { formatDubaiDate } from './headerMeta'
import { useBi, useFetch, type Bi } from './lib'

interface Gate { gate_id: string; gate_type: string; description: Bi; status: string; panel_status: string; panel_label: Bi; fallback_path: string | null; version: number; effective_from: string; changed_by: string | null; change_reason: string | null; evidence_refs: string[] }
interface Increment { id: string; name: Bi; status: string; status_label: Bi; entry_gate: Bi; manual_fallback: Bi; demo_outcome: Bi; stories: { order: number; story_id: string; title: string; gated?: boolean }[]; gates: Gate[]; demo_done: { recorded_at: string } | null; released_at: string | null; last_changed_at: string; delivery_measures: { gated_off: number; stories_total: number; stories_live: number } }
interface PhaseMap { published: boolean; increments: Increment[]; behind_switches: Record<string, boolean> }

const INC_ICON: Record<string, string> = { not_started: '○', in_build: '🔧', manual_path_live: '✋', live: '✓', demo_done: '⚑', not_assigned: '—' }
const GATE_ICON: Record<string, string> = { not_met: '🔒', in_progress: '⌛', met: '✓', not_needed_in_pilot: '⊖' }
const GATE_STATUSES = ['not_yet_confirmed', 'evidence_received', 'open', 'closed', 'fallback_active', 'not_needed_in_pilot']

/** SC14 'Phase map and gates' tab (E1-S7): increments, gate register with versions, demo-done and release actions. */
export default function PhaseMapTab() {
  const { t, i18n } = useTranslation('det')
  const { tx } = useBi()
  const { me } = useAuth()
  const { data, error, loading, loadedAt, reload } = useFetch<PhaseMap>('/api/admin/phases')
  const [gateDialog, setGateDialog] = useState<Gate | null>(null)
  const [demoDialog, setDemoDialog] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const canChange = !!me && (me.staff_permissions.includes('integrations.manage') || me.staff_permissions.includes('det.phase_switches'))
  const canDemo = !!me && me.staff_permissions.includes('phase_map.record_demo')
  if (loading && !data) return <div aria-busy="true"><p>{t('wl_loading')}</p><Skeleton rows={4} /></div>
  if (error && !data) return <Message kind="error">{t('phase_error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message>
  if (!data || !data.published) return <Message kind="info">{t('phase_empty')}</Message>
  const incTone = (s: string) => (s === 'live' || s === 'demo_done' ? 'ok' : s === 'manual_path_live' ? 'info' : s === 'in_build' ? 'attention' : 'neutral')
  const gateTone = (s: string) => (s === 'met' ? 'ok' : s === 'in_progress' ? 'attention' : s === 'not_needed_in_pilot' ? 'neutral' : 'urgent')
  const releaseAction = (inc: Increment) => async () => { try { await post(`/api/admin/phases/${inc.id}/release`); setMsg({ kind: 'success', text: t('register_loaded') }); reload() } catch (e) { setMsg({ kind: 'error', text: (e as Error).message }) } }
  return (
    <div>
      <p className="det-note"><Icon name="info" size={16} />{t('phases_intro')}</p>
      {error && data && <Message kind="warning">{t('gates_error')} {loadedAt && t('last_known', { date: formatDateTime(loadedAt, i18n.language) })} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message>}
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <ol className="det-phases">
        {data.increments.map((inc) => (
          <li key={inc.id} className="det-phase">
            <Panel id={`inc-${inc.id}`} title={<span className="det-phase-title"><span className="det-phase-id"><bdi dir="ltr">{inc.id}</bdi></span>{tx(inc.name)} <Chip tone={incTone(inc.status)} icon={INC_ICON[inc.status]}>{tx(inc.status_label)}</Chip></span>}
              actions={canDemo && !inc.demo_done ? <Button variant="secondary" className="det-rowbtn" onClick={() => setDemoDialog(inc.id)}>{t('record_demo')}</Button> : canDemo && !inc.released_at ? <Button variant="secondary" className="det-rowbtn" onClick={releaseAction(inc)}>{t('release_increment')}</Button> : undefined}>
              <dl className="det-phase-grid">
                <div><dt>{t('entry_gate')}</dt><dd>{tx(inc.entry_gate)}</dd></div>
                <div><dt>{t('fallback')}</dt><dd>{tx(inc.manual_fallback)}</dd></div>
                <div><dt>{t('demo_outcome')}</dt><dd>{tx(inc.demo_outcome)}</dd></div>
                {inc.demo_done && <div><dt>{t('demo_done_label')}</dt><dd>{t('demo_recorded', { date: formatDate(inc.demo_done.recorded_at, i18n.language) })}</dd></div>}
              </dl>
              <div className="table-compact det-table">
              <Table headers={[t('entry_gate'), t('col_status'), t('col_version'), t('col_date'), t('col_reason'), t('evidence_ref')]}>
                {inc.gates.map((g) => (
                  <tr key={g.gate_id}>
                    <td className="det-wrap">{tx(g.description)}{g.gate_type === 'fallback' && <span className="det-cell-sub"><Chip tone="info" icon="✋">{t('fallback')}</Chip></span>}</td>
                    <td><Chip tone={gateTone(g.panel_status)} icon={GATE_ICON[g.panel_status]}>{tx(g.panel_label)}</Chip><span className="det-cell-sub"><bdi dir="ltr">{g.status}</bdi></span></td>
                    <td className="nowrap"><bdi dir="ltr">v{g.version}</bdi></td>
                    <td className="date-cell" title={formatDateTime(g.effective_from, i18n.language)}>{formatDubaiDate(g.effective_from, i18n.language)}</td>
                    <td className="det-wrap">{g.change_reason}</td>
                    <td>
                      {g.evidence_refs.map((r) => <div key={r} className="nowrap"><bdi dir="ltr">{r}</bdi></div>)}
                      {canChange && <Button variant="link" onClick={() => setGateDialog(g)} disabled={!!error} title={error ? t('controls_disabled') : undefined}>{t('change_gate')}</Button>}
                    </td>
                  </tr>
                ))}
              </Table>
              </div>
              <Disclosure summary={<>{t('stories')} <span className="hint">({inc.delivery_measures.gated_off} {t('gated')} / {inc.delivery_measures.stories_total})</span></>}>
                <ol className="det-phase-stories">
                  {inc.stories.map((s) => (
                    <li key={s.story_id}><bdi dir="ltr">{s.story_id}</bdi> {s.title} {s.gated && <Chip tone="neutral" icon="🔒">{t('gated')}</Chip>}</li>
                  ))}
                </ol>
              </Disclosure>
              <p className="det-phase-foot">{t('status_changed', { date: formatDate(inc.last_changed_at, i18n.language) })}</p>
            </Panel>
          </li>
        ))}
      </ol>
      <Panel title={t('behind_switches')} className="det-switches-panel">
        <div className="det-switches">
          {Object.entries(data.behind_switches).map(([k, v]) => <Chip key={k} tone={v ? 'ok' : 'neutral'}>{k.replace(/_/g, ' ')}: {v ? 'ON' : 'OFF'}</Chip>)}
        </div>
      </Panel>
      {gateDialog && <GateDialog gate={gateDialog} onClose={() => setGateDialog(null)} onDone={() => { setGateDialog(null); reload() }} />}
      {demoDialog && <DemoDialog increment={demoDialog} onClose={() => setDemoDialog(null)} onDone={() => { setDemoDialog(null); reload() }} />}
    </div>
  )
}

function GateDialog({ gate, onClose, onDone }: { gate: Gate; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation('det')
  const { t: tc } = useTranslation()
  const [status, setStatus] = useState(gate.status)
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')
  const [approved, setApproved] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const submit = async () => {
    try {
      await post(`/api/admin/gates/${gate.gate_id}/status`, { status, change_reason: reason, evidence_ref: evidence || null, approved_by: approved || null })
      onDone()
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  return (
    <Dialog open title={t('change_gate')} onClose={onClose}>
      {err && <Message kind="error">{err}</Message>}
      <Field label={t('col_status')} id="gate-status">
        <select id="gate-status" value={status} onChange={(e) => setStatus(e.target.value)}>
          {GATE_STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
      </Field>
      <Field label={t('evidence_ref')} id="gate-evidence"><input id="gate-evidence" value={evidence} onChange={(e) => setEvidence(e.target.value)} dir="ltr" /></Field>
      <Field label={t('approved_by')} id="gate-approved"><input id="gate-approved" value={approved} onChange={(e) => setApproved(e.target.value)} dir="ltr" /></Field>
      <Field label={t('change_reason')} id="gate-reason" required><input id="gate-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <div className="actions">
        <Button onClick={submit} disabled={!reason}>{t('change_gate')}</Button>
        <Button variant="secondary" onClick={onClose}>{tc('common.cancel')}</Button>
      </div>
    </Dialog>
  )
}

function DemoDialog({ increment, onClose, onDone }: { increment: string; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation('det')
  const { t: tc } = useTranslation()
  const [crit, setCrit] = useState<Record<string, boolean>>({ a: false, b: false, c: false, d: false })
  const [err, setErr] = useState<string | null>(null)
  const submit = async () => {
    try {
      await post(`/api/admin/phases/${increment}/demo-done`, { criteria: crit })
      onDone()
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  return (
    <Dialog open title={`${t('record_demo')} - ${increment}`} onClose={onClose}>
      {err && <Message kind="error">{err}</Message>}
      {(['a', 'b', 'c', 'd'] as const).map((k) => (
        <label key={k} className="check">
          <input type="checkbox" checked={crit[k]} onChange={(e) => setCrit({ ...crit, [k]: e.target.checked })} /> {t(`demo_criteria.${k}`)}
        </label>
      ))}
      <div className="actions">
        <Button onClick={submit} disabled={!Object.values(crit).every(Boolean)}>{t('record_demo')}</Button>
        <Button variant="secondary" onClick={onClose}>{tc('common.cancel')}</Button>
      </div>
    </Dialog>
  )
}
