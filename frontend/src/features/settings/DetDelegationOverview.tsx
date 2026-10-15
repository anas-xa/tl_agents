import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Message, Panel, Skeleton } from '../../components/ui'
import { get } from '../../lib/api'
import { formatNumber, formatPercent } from '../../lib/format'

type Cell = { suppressed: boolean; value?: number; display?: string; percent?: number; complement?: boolean; not_enabled?: boolean }
interface Overview { as_of: string; period_days: number; period_level: 'month' | 'quarter'; min_group_size: number; companies_with_active_delegate: Cell; pending_invitations: Cell; expired_invitations: Cell; removals_by_reason: Record<string, Cell>; quarantine_events: Cell; no_owner_companies: Cell; delegated_rights: Record<string, Cell>; phase_note: string }

function CellView({ cell, label }: { cell: Cell; label: string }) {
  const { t, i18n } = useTranslation('settings')
  const lang = i18n.language
  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      {cell.not_enabled ? (
        <div className="stat">{t('det_not_enabled')}</div>
      ) : cell.suppressed ? (
        <div>
          <div className="stat"><span aria-hidden="true">🔒</span> {cell.display}</div>
          <div className="helper">{t('suppressed')}</div>
        </div>
      ) : (
        <div className="stat">{formatNumber(cell.value, lang)}{cell.percent !== undefined && <span className="muted"> ({formatPercent(cell.percent, lang)})</span>}</div>
      )}
    </div>
  )
}

/** SC14 'Delegation overview' block: counters only; suppressed cells show the lock icon and the full text in the card. */
export default function DetDelegationOverview() {
  const { t } = useTranslation('settings')
  const [data, setData] = useState<Overview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    get<Overview>('/api/det/delegation-overview').then(setData).catch((e) => setErr(e.message))
  }, [])
  if (err) return <Message kind="error">{err}</Message>
  if (!data) return <Skeleton rows={3} />
  return (
    <Panel title={t('det_title')} id="delegation-overview">
      <p className="muted">{t('det_as_of', { when: data.as_of })} · {t('det_level')}: {data.period_level === 'quarter' ? t('det_quarter') : t('det_month')}</p>
      <p className="helper">{t('det_stub')}</p>
      <div className="grid">
        <CellView cell={data.companies_with_active_delegate} label={t('det_c1')} />
        <CellView cell={data.pending_invitations} label={t('det_c2')} />
        <CellView cell={data.expired_invitations} label={t('det_c3')} />
        <CellView cell={data.quarantine_events} label={t('det_c5')} />
        <CellView cell={data.no_owner_companies} label={t('det_c6')} />
      </div>
      <h3>{t('det_c4')}</h3>
      <div className="grid">
        {Object.entries(data.removals_by_reason).map(([k, c]) => <CellView key={k} cell={c} label={t(`det_${k}`)} />)}
      </div>
      <h3>{t('det_c7')}</h3>
      <div className="grid">
        {Object.entries(data.delegated_rights).map(([k, c]) => <CellView key={k} cell={c} label={t(`fn_${k}`)} />)}
      </div>
    </Panel>
  )
}
