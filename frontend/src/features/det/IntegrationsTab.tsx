import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Chip, Dialog, Field, Message, Panel, Skeleton, Table } from '../../components/ui'
import { ApiError, post } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { srOnly, useBi, useFetch, type Bi } from './lib'

interface Item { item_id: string; text_en?: string; text_ar?: string; item_type: string; tag?: string | null; owner_name?: string | null; evidence_reference?: string | null; evidence_date?: string | null; approver_identity?: string | null; complete: boolean; missing?: string[] }
interface Row { row_id: string; integration: string; name: Bi; switch_key: string; switch_state: 'ON' | 'OFF'; phase: number; fallback_path: string | null; status: string; mock: boolean; progress: { n: number; m: number; label: Bi; word: 'Complete' | 'Incomplete' | 'Not started' }; version: number; updated_at: string; items: Item[]; live: boolean; switch_history?: { state: string; changed_at: string; reason: string }[] }
interface Register { rows: Row[]; evidence_detail: boolean; k11: { headline: Bi | null; secondary: Bi | null; bank_routes_live: string[] }; outside_scope_switches: Record<string, boolean> }

/** SC14 integration register (E1-S8): read-only table with switch badge and 'n of m' progress; row drawer; switch controls. */
export default function IntegrationsTab() {
  const { t, i18n } = useTranslation('det')
  const { t: tc } = useTranslation()
  const { tx } = useBi()
  const { me } = useAuth()
  const { data, error, loading, loadedAt, reload } = useFetch<Register>('/api/admin/integrations')
  const [open, setOpen] = useState<Row | null>(null)
  const [confirmOff, setConfirmOff] = useState<Row | null>(null)
  const [live, setLive] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const canManage = !!me && me.staff_permissions.includes('integrations.manage')
  const canSwitch = canManage || (!!me && me.staff_permissions.includes('det.phase_switches'))
  const toggle = async (row: Row, state: 'ON' | 'OFF', reason: string) => {
    try {
      await post(`/api/admin/integrations/switches/${row.switch_key}`, { state, reason })
      setLive(state === 'OFF' ? t('switch_turned_off') : t('register_loaded'))
      setMsg(null)
      reload()
    } catch (e) {
      setMsg(e instanceof ApiError && e.code === 'ROW_NOT_CONFIRMED_LIVE' ? t('switch_on_disabled') : (e as Error).message)
    }
  }
  if (loading && !data) return <div aria-busy="true"><span style={srOnly}>{t('loading_register')}</span><Skeleton rows={5} /></div>
  if (error && !data) return <Message kind="error">{t('register_error', { when: '—' })} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message>
  if (!data) return null
  const statusTone = (s: string) => (s === 'confirmed_live' ? 'ok' : s === 'evidence_pending' ? 'attention' : s === 'expired' ? 'urgent' : 'neutral')
  return (
    <div>
      <div aria-live="polite" style={srOnly}>{live}</div>
      <p>{t('integrations_intro')}</p>
      {error && loadedAt && <Message kind="warning">{t('register_error', { when: formatDateTime(loadedAt, i18n.language) })} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message>}
      {msg && <Message kind="error">{msg}</Message>}
      {!data.evidence_detail && <Message kind="info">{t('no_evidence_detail')}</Message>}
      {data.rows.length === 0 ? (
        <Message kind="info">{t('register_empty')} {t('register_empty_owners')}</Message>
      ) : (
        <Panel title={t('integrations_title')} actions={canManage ? <Button variant="secondary" onClick={async () => { await post('/api/admin/integrations/daily-check'); reload() }}>{t('daily_check')}</Button> : undefined}>
          <Table headers={[t('col_integration'), t('col_phase'), t('col_switch'), t('col_status'), t('col_progress'), t('col_last_change')]}>
            {data.rows.map((r) => (
              <tr key={r.row_id}>
                <td>
                  <Button variant="link" onClick={() => setOpen(r)}>{tx(r.name)}</Button> {r.mock && <Chip tone="draft">{t('mock')}</Chip>}
                </td>
                <td>{r.phase}</td>
                <td><Chip tone={r.switch_state === 'ON' ? 'ok' : 'neutral'} icon={r.switch_state === 'ON' ? '●' : '○'}>{r.switch_state}</Chip></td>
                <td><Chip tone={statusTone(r.status)}>{t(`row_status.${r.status}`, { defaultValue: r.status })}</Chip></td>
                <td>
                  {tx(r.progress.label)} <Chip tone={r.progress.word === 'Complete' ? 'ok' : r.progress.word === 'Incomplete' ? 'attention' : 'neutral'}>{t(`progress_word.${r.progress.word}`)}</Chip>
                  <div aria-hidden="true" style={{ display: 'flex', gap: 2, marginTop: 4 }}>
                    {Array.from({ length: r.progress.m }).map((_, i) => <span key={i} style={{ width: 14, height: 6, borderRadius: 3, background: i < r.progress.n ? 'var(--ok)' : 'var(--border)' }} />)}
                  </div>
                </td>
                <td>{formatDateTime(r.updated_at, i18n.language)} <span className="hint">v{r.version}</span></td>
              </tr>
            ))}
          </Table>
        </Panel>
      )}
      <Panel title={t('k11_title')}>
        {data.k11.headline ? <p><Chip tone="neutral">{tx(data.k11.headline)}</Chip> {data.k11.secondary && tx(data.k11.secondary)}</p> : <p>{data.k11.bank_routes_live.join(', ')}</p>}
      </Panel>
      {open && (
        <Dialog open title={tx(open.name)} onClose={() => setOpen(null)} labelledBy="row-drawer-title">
          <p><Chip tone={statusTone(open.status)}>{t(`row_status.${open.status}`, { defaultValue: open.status })}</Chip> <Chip tone={open.switch_state === 'ON' ? 'ok' : 'neutral'}>{open.switch_state}</Chip> {tx(open.progress.label)}</p>
          {open.fallback_path && <p className="hint">{t('fallback')}: {open.fallback_path}</p>}
          {open.items.length === 0 ? (
            <p>{t('row_detail_empty')}</p>
          ) : (
            <ul>
              {open.items.map((it) => (
                <li key={it.item_id} style={{ marginBottom: 8 }}>
                  <Chip tone={it.complete ? 'ok' : 'neutral'}>{it.complete ? t('progress_word.Complete') : t('progress_word.Incomplete')}</Chip>{' '}
                  {data.evidence_detail ? (i18n.language.startsWith('ar') ? it.text_ar : it.text_en) : <bdi dir="ltr">{it.item_id}</bdi>} {it.tag && <Chip tone="attention">{it.tag}</Chip>}
                  {data.evidence_detail && !it.complete && it.missing && it.missing.length > 0 && <div className="notice-tbc">{t('missing', { field: it.missing[0] })}</div>}
                  {data.evidence_detail && it.complete && <div className="hint"><bdi dir="ltr">{it.evidence_reference}</bdi> · {it.evidence_date} · {it.approver_identity}</div>}
                  {canManage && !it.complete && <CompleteItem row={open} item={it} onDone={() => { setOpen(null); reload() }} />}
                </li>
              ))}
            </ul>
          )}
          {data.evidence_detail && open.switch_history && open.switch_history.length > 0 && (
            <details>
              <summary>{t('switch_history')}</summary>
              <ul>{open.switch_history.map((h, i) => <li key={i}>{h.state} · {formatDateTime(h.changed_at, i18n.language)} · {h.reason}</li>)}</ul>
            </details>
          )}
          <div className="actions">
            {canManage && open.status !== 'confirmed_live' && <Button onClick={async () => { try { await post(`/api/admin/integrations/${open.row_id}/status`, { status: 'confirmed_live', change_reason: 'all evidence present' }); setOpen(null); reload() } catch (e) { setMsg((e as Error).message) } }} disabled={open.progress.n < open.progress.m} title={open.progress.n < open.progress.m ? t('missing', { field: t('col_progress') }) : undefined}>{t('confirm_live')}</Button>}
            {canSwitch && open.switch_state === 'OFF' && <Button onClick={() => toggle(open, 'ON', 'admin')} disabled={open.status !== 'confirmed_live'} title={open.status !== 'confirmed_live' ? t('switch_on_disabled') : undefined}>{t('switch_on')}</Button>}
            {canSwitch && open.switch_state === 'ON' && <Button variant="danger" onClick={() => { setConfirmOff(open); setOpen(null) }}>{t('switch_off')}</Button>}
            <Button variant="secondary" onClick={() => setOpen(null)}>{tc('common.close')}</Button>
          </div>
        </Dialog>
      )}
      {confirmOff && (
        <Dialog open title={t('switch_off')} onClose={() => setConfirmOff(null)}>
          <p>{t('switch_off_confirm')}</p>
          <div className="actions">
            <Button variant="danger" onClick={() => { toggle(confirmOff, 'OFF', 'admin switch-off'); setConfirmOff(null) }}>{t('switch_off')}</Button>
            <Button variant="secondary" onClick={() => setConfirmOff(null)}>{tc('common.cancel')}</Button>
          </div>
        </Dialog>
      )}
    </div>
  )
}

function CompleteItem({ row, item, onDone }: { row: Row; item: Item; onDone: () => void }) {
  const { t } = useTranslation('det')
  const [f, setF] = useState({ owner_name: item.owner_name ?? '', owner_role: '', evidence_reference: item.evidence_reference ?? '', evidence_date: item.evidence_date ?? '', approver_identity: item.approver_identity ?? '' })
  const [err, setErr] = useState<string | null>(null)
  const missing = (['owner_name', 'evidence_reference', 'evidence_date', 'approver_identity'] as const).filter((k) => !f[k])
  return (
    <details>
      <summary>{t('complete_item')}</summary>
      {err && <Message kind="error">{err}</Message>}
      {(Object.keys(f) as (keyof typeof f)[]).map((k) => (
        <Field key={k} label={k.replace(/_/g, ' ')} id={`${row.row_id}-${item.item_id}-${k}`}>
          <input id={`${row.row_id}-${item.item_id}-${k}`} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} dir="ltr" />
        </Field>
      ))}
      <Button disabled={missing.length > 0} title={missing.length ? t('missing', { field: missing[0] }) : undefined} onClick={async () => { try { await post(`/api/admin/integrations/${row.row_id}/items/${item.item_id}/complete`, f); onDone() } catch (e) { setErr((e as Error).message) } }}>{t('complete_item')}</Button>
      {missing.length > 0 && <div className="notice-tbc">{t('missing', { field: missing[0] })}</div>}
    </details>
  )
}
