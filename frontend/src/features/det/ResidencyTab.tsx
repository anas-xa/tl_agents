import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon, type IconName } from '../../components/Icon'
import { Button, Chip, Message, Panel, Skeleton, Table } from '../../components/ui'
import { post } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { useDetHeaderMeta } from './headerMeta'
import { srOnly, useBi, useFetch, type Bi } from './lib'
import { MetaLine } from './ui'

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
  const lastCheck = data.last_successful_check_at ? (
    <MetaLine
      items={[
        t('last_successful_check', { when: formatDateTime(data.last_successful_check_at, i18n.language) }),
        stale ? <Chip key="s" tone="attention">{t('stale')}</Chip> : null,
        data.inventory?.is_demo ? <Chip key="d" tone="draft">{t('demo_data')}</Chip> : null,
      ]}
    />
  ) : null
  return <ResidencyView {...{ data, stale, cardTone, cardLabel, cardRefresh, refresh, refreshing, announce, setAnnounce, canManage, statement: statement.data, lastCheck, showAuditLink: !!me?.staff_permissions.includes('audit_trail.view') }} />
}

const CARD_ICON: Record<string, IconName> = { hosting: 'building', encryption: 'lock', egress: 'shield', ai_models: 'sparkle', release: 'file-check' }

function ResidencyView({ data, stale, cardTone, cardLabel, cardRefresh, refresh, refreshing, announce, setAnnounce, canManage, statement, lastCheck, showAuditLink }: {
  data: Summary; stale: boolean; cardTone: (k: keyof Summary['cards']) => 'ok' | 'urgent' | 'attention' | 'neutral'; cardLabel: Record<keyof Summary['cards'], string>; cardRefresh: boolean
  refresh: () => void; refreshing: boolean; announce: string; setAnnounce: (s: string) => void; canManage: boolean; statement: Statement | null; lastCheck: React.ReactNode; showAuditLink: boolean
}) {
  const { t, i18n } = useTranslation('det')
  const { tx } = useBi()
  const inHeader = useDetHeaderMeta(lastCheck, [data.last_successful_check_at, stale, data.inventory?.is_demo, i18n.language])
  const passCount = data.components.filter((c) => c.status === 'pass').length
  const rd = data.release_decision
  const releaseOk = rd?.result === 'pass' && !stale
  return (
    <div>
      <div aria-live="polite" style={srOnly}>{announce}</div>
      {!inHeader && lastCheck && <p>{lastCheck}</p>}
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
      <div className="det-card-grid det-card-grid-5">
        {(Object.keys(cardLabel) as (keyof Summary['cards'])[]).map((key) => (
          <div className={`card det-status-card det-status-card-${cardTone(key)}`} key={key}>
            <h3><Icon name={CARD_ICON[key]} size={18} />{cardLabel[key]}</h3>
            <p><Chip tone={cardTone(key)}>{tx(data.cards[key])}</Chip></p>
          </div>
        ))}
      </div>
      <p className="det-note"><Icon name="info" size={16} />{t('gloss_egress')}</p>
      <div className="det-two">
        <Panel title={t('inventory_title')} className={data.components.length ? 'det-panel-flush' : undefined} actions={<>{data.components.length > 0 && <span className="hint">{t('res_pass_n', { n: passCount, m: data.components.length })}</span>}{canManage && data.state !== 'no_inventory' && <Button variant="secondary" className="det-rowbtn" onClick={refresh} disabled={refreshing}>{t('refresh')}</Button>}</>}>
          {data.components.length === 0 ? (
            <p>{t('not_confirmed')}</p>
          ) : (
            <div className="table-compact det-table">
            <Table headers={[t('col_component'), t('col_type'), t('col_location'), t('col_status')]}>
              {data.components.map((c) => (
                <tr key={c.component_id}>
                  <td><bdi dir="ltr">{c.name}</bdi></td>
                  <td className="nowrap"><bdi dir="ltr">{c.component_type}</bdi></td>
                  <td className="nowrap"><bdi dir="ltr">{c.hosting_location}</bdi></td>
                  <td>
                    <Chip tone={stale ? 'neutral' : c.status === 'pass' ? 'ok' : c.status === 'fail' ? 'urgent' : 'attention'}>{stale ? t('not_confirmed') : t(`status_${c.status}`)}</Chip>
                  </td>
                </tr>
              ))}
            </Table>
            </div>
          )}
        </Panel>
        <Panel title={t('release_title')} actions={rd ? <Chip tone={releaseOk ? 'ok' : 'urgent'} icon={releaseOk ? '✓' : '!'}>{releaseOk ? t('release_pass') : t('release_blocked')}</Chip> : undefined}>
          {!rd ? (
            <p>{t('not_yet_available')}</p>
          ) : (
            <>
              <p className="det-note"><Icon name="clock" size={16} /><span className="nowrap">{formatDateTime(rd.decided_at, i18n.language)}</span></p>
              {(rd.result === 'blocked' || stale) && (
                <div className="det-callout det-callout-urgent">
                  <ul>
                    {(stale && rd.result === 'pass' ? [{ code: 'STALE', en: 'Blocked: the inventory is stale and cannot count as a pass', ar: 'محظور: الجرد قديم ولا يمكن احتسابه كاجتياز' }] : rd.reasons).map((r, i) => (
                      <li key={i}>{tx(r)}</li>
                    ))}
                  </ul>
                  {rd.next_step && <p style={{ margin: '8px 0 0' }}><strong>{tx(rd.next_step)}</strong></p>}
                </div>
              )}
              {rd.next_step && !(rd.result === 'blocked' || stale) && <p><strong>{tx(rd.next_step)}</strong></p>}
              <ul className="det-checks det-checks-1">
                {rd.checks.map((c) => (
                  <li key={c.check}>
                    <span>{t(`check_names.${c.check}`, { defaultValue: c.check })}</span>
                    <Chip tone={c.result === 'pass' ? 'ok' : c.result === 'fail' ? 'urgent' : 'neutral'}>{c.result === 'not_run' ? t('check_not_run') : c.result === 'pass' ? t('status_pass') : t('status_fail')}</Chip>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>
      </div>
      <div className="det-card-grid det-card-grid-3" style={{ marginTop: 20 }}>
        <div className="card det-status-card">
          <h3><Icon name="shield" size={18} />{t('card_egress')}</h3>
          <p>{t('egress_alerts', { total: data.egress_alerts.total, open: data.egress_alerts.open })}</p>
          {showAuditLink && <Link to="/admin/audit-trail">{t('link_sc15')}</Link>}
        </div>
        <div className="card det-status-card">
          <h3><Icon name="lock" size={18} />{t('key_usage')}</h3>
          <p>{t('keys_registered', { n: data.key_usage.keys, due: data.key_usage.due_within_30_days })}</p>
        </div>
        <div className="card det-status-card">
          <h3><Icon name="file" size={18} />{t('owner_statement_preview')}</h3>
          {statement && <p><Chip tone={statement.state === 'approved' ? 'ok' : 'neutral'}>{t(`statement_state.${statement.state}`)}</Chip></p>}
          {statement && <p>{tx(statement as Bi)}</p>}
        </div>
      </div>
      <div className="actions">
        <Button variant="secondary" disabled title={t('evidence_export_later')}><Icon name="download" size={18} />{t('evidence_export')} ({t('evidence_export_later')})</Button>
      </div>
    </div>
  )
}
