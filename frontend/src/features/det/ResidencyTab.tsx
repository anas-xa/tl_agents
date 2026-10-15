import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Message, Panel, Skeleton, Table } from '../../components/ui'
import { post } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { srOnly, useBi, useFetch, type Bi } from './lib'

interface Component { component_id: string; name: string; component_type: string; hosting_location: string; status: 'pass' | 'fail' | 'pending'; fail_reasons: string[]; backup_location: string | null; support_access_location: string | null }
interface Decision { release_id: string; result: 'pass' | 'blocked'; reasons: { code: string; component?: string; en: string; ar: string }[]; next_step: Bi | null; checks: { check: string; result: string }[]; decided_at: string }
interface Summary {
  state: 'ok' | 'no_inventory' | 'generation_failed' | 'stale'
  message: Bi | null
  inventory: { inventory_version: string; generated_at: string; checklist_version: string; check_mode: string; stale: boolean; is_demo: boolean } | null
  last_successful_check_at: string | null
  cards: Record<'hosting' | 'encryption' | 'egress' | 'ai_models' | 'release', Bi>
  all_pass: boolean
  components: Component[]
  release_decision: Decision | null
  egress_alerts: { total: number; open: number }
  key_usage: { keys: number; due_within_30_days: number }
  evidence_export: { available: boolean; label: string }
  viewer: { can_manage: boolean; counts_only: boolean }
}
interface Statement { state: string; en: string; ar: string }

/** SC14 'Data residency and security' panel (E1-S4): safe core states, never 'Pass' while empty or stale. */
export default function ResidencyTab() {
  const { t, i18n } = useTranslation('det')
  const { tx } = useBi()
  const { me } = useAuth()
  const { data, error, reload, setData } = useFetch<Summary>('/api/hosting/residency')
  const statement = useFetch<Statement>('/api/hosting/residency-statement')
  const [refreshing, setRefreshing] = useState(false)
  const [announce, setAnnounce] = useState('')
  const canManage = data?.viewer.can_manage ?? false
  const refresh = async () => {
    setRefreshing(true)
    try {
      const out = await post<{ summary: Summary }>('/api/hosting/residency/refresh')
      setData(out.summary)
      statement.reload()
      setAnnounce(t('register_loaded'))
    } catch {
      await reload()
    } finally {
      setRefreshing(false)
    }
  }
  if (error && !data) {
    return (
      <Message kind="error">
        {error.message.includes('access') || (error as { status?: number }).status === 403 ? t('no_access') : t('phase_error')}
      </Message>
    )
  }
  if (!data) return <div aria-busy="true"><p>{t('checking_latest')}</p><Skeleton rows={5} /></div>
  const stale = data.inventory?.stale || data.state === 'stale' || data.state === 'generation_failed'
  const cardTone = (key: keyof Summary['cards']) => {
    if (!data.inventory || stale) return 'neutral'
    if (key === 'release') return data.release_decision?.result === 'pass' ? 'ok' : 'urgent'
    if (key === 'hosting') return data.all_pass ? 'ok' : 'urgent'
    if (key === 'egress') return data.egress_alerts.open > 0 ? 'attention' : 'neutral'
    return 'ok'
  }
  const cardLabel: Record<keyof Summary['cards'], string> = { hosting: t('card_hosting'), encryption: t('card_encryption'), egress: t('card_egress'), ai_models: t('card_ai'), release: t('card_release') }
  const cardRefresh = data.state === 'no_inventory' || data.state === 'generation_failed' || canManage
  return (
    <div>
      <div aria-live="polite" style={srOnly}>{announce}</div>
      {refreshing && <p aria-busy="true"><Chip tone="info">{t('refreshing')}</Chip> {t('checking_latest')}</p>}
      {data.state === 'generation_failed' && data.message && (
        <Message kind="error">
          {tx(data.message)}
          <div className="actions">
            {cardRefresh && <Button onClick={refresh} disabled={refreshing}>{t('try_again')}</Button>}
            <Button variant="secondary" onClick={() => setAnnounce(t('raise_platform'))}>{t('raise_platform')}</Button>
          </div>
        </Message>
      )}
      {data.state === 'no_inventory' && data.message && (
        <Message kind="info">
          {tx(data.message)}
          <div className="actions"><Button variant="secondary" onClick={refresh} disabled={refreshing}>{t('refresh')}</Button></div>
        </Message>
      )}
      {data.inventory && data.components.length === 0 && data.message && <Message kind="warning">{tx(data.message)}</Message>}
      {data.last_successful_check_at && (
        <p>
          {t('last_successful_check', { when: formatDateTime(data.last_successful_check_at, i18n.language) })}
          {stale && <> <Chip tone="attention">{t('stale')}</Chip></>}
          {data.inventory?.is_demo && <> <Chip tone="draft">{t('demo_data')}</Chip></>}
        </p>
      )}
      <div className="grid">
        {(Object.keys(cardLabel) as (keyof Summary['cards'])[]).map((key) => (
          <div className="card" key={key}>
            <h3>{cardLabel[key]}</h3>
            <Chip tone={cardTone(key)}>{tx(data.cards[key])}</Chip>
          </div>
        ))}
      </div>
      <p className="hint">{t('gloss_egress')}</p>
      <Panel title={t('inventory_title')} actions={canManage && data.state !== 'no_inventory' ? <Button variant="secondary" onClick={refresh} disabled={refreshing}>{t('refresh')}</Button> : undefined}>
        {data.components.length === 0 ? (
          <p>{t('not_confirmed')}</p>
        ) : (
          <Table headers={[t('col_component'), t('col_type'), t('col_location'), t('col_status')]}>
            {data.components.map((c) => (
              <tr key={c.component_id}>
                <td><bdi dir="ltr">{c.name}</bdi></td>
                <td><bdi dir="ltr">{c.component_type}</bdi></td>
                <td><bdi dir="ltr">{c.hosting_location}</bdi></td>
                <td>
                  <Chip tone={stale ? 'neutral' : c.status === 'pass' ? 'ok' : c.status === 'fail' ? 'urgent' : 'attention'}>{stale ? t('not_confirmed') : t(`status_${c.status}`)}</Chip>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
      <Panel title={t('release_title')}>
        {!data.release_decision ? (
          <p>{t('not_yet_available')}</p>
        ) : (
          <>
            <p>
              <Chip tone={data.release_decision.result === 'pass' && !stale ? 'ok' : 'urgent'}>
                {data.release_decision.result === 'pass' && !stale ? t('release_pass') : t('release_blocked')}
              </Chip>{' '}
              {formatDateTime(data.release_decision.decided_at, i18n.language)}
            </p>
            {(data.release_decision.result === 'blocked' || stale) && (
              <ul>
                {(stale && data.release_decision.result === 'pass' ? [{ code: 'STALE', en: 'Blocked: the inventory is stale and cannot count as a pass', ar: 'محظور: الجرد قديم ولا يمكن احتسابه كاجتياز' }] : data.release_decision.reasons).map((r, i) => (
                  <li key={i}>{tx(r)}</li>
                ))}
              </ul>
            )}
            {data.release_decision.next_step && <p><strong>{tx(data.release_decision.next_step)}</strong></p>}
            <Table headers={[t('col_status'), t('col_component')]}>
              {data.release_decision.checks.map((c) => (
                <tr key={c.check}>
                  <td><Chip tone={c.result === 'pass' ? 'ok' : c.result === 'fail' ? 'urgent' : 'neutral'}>{c.result === 'not_run' ? t('check_not_run') : c.result === 'pass' ? t('status_pass') : t('status_fail')}</Chip></td>
                  <td>{t(`check_names.${c.check}`, { defaultValue: c.check })}</td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </Panel>
      <div className="grid">
        <div className="card">
          <h3>{t('card_egress')}</h3>
          <p>{t('egress_alerts', { total: data.egress_alerts.total, open: data.egress_alerts.open })}</p>
          {me?.staff_permissions.includes('audit_trail.view') && <Link to="/admin/audit-trail">{t('link_sc15')}</Link>}
        </div>
        <div className="card">
          <h3>{t('key_usage')}</h3>
          <p>{t('keys_registered', { n: data.key_usage.keys, due: data.key_usage.due_within_30_days })}</p>
        </div>
        <div className="card">
          <h3>{t('owner_statement_preview')}</h3>
          {statement.data && <p><Chip tone={statement.data.state === 'approved' ? 'ok' : 'neutral'}>{t(`statement_state.${statement.data.state}`)}</Chip> {tx(statement.data as Bi)}</p>}
        </div>
      </div>
      <div className="actions">
        <Button variant="secondary" disabled title={t('evidence_export_later')}>{t('evidence_export')} ({t('evidence_export_later')})</Button>
      </div>
    </div>
  )
}
