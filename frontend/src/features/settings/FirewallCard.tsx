import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Chip, Message, Panel, Skeleton } from '../../components/ui'
import { get } from '../../lib/api'
import { formatDateTime } from '../../lib/format'

export interface FirewallRow { id: string; engagement_id: string; company_id: string; firm: string | null; result: 'conflict_found' | 'no_conflict_found_in_det_records'; rule_version: string; links_used: number; independence_declared_at: string | null; manual_conflict_flags: number; status: 'active' | 'suspended'; evaluated_at: string }

/**
 * Auditor firewall result card (for the audit epic). Wording is 'no conflict found in DET records', never
 * 'independent'. Pass `record` to render a known result, or `companyId` (+ optional `engagementId`) to fetch.
 */
export default function FirewallCard({ record, companyId, engagementId }: { record?: FirewallRow; companyId?: string; engagementId?: string }) {
  const { t, i18n } = useTranslation('settings')
  const [rows, setRows] = useState<FirewallRow[] | null>(record ? [record] : null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (record || !companyId) return
    get<FirewallRow[]>(`/api/companies/${companyId}/firewall`).then(setRows).catch((e) => setErr(e.message))
  }, [record, companyId])
  if (err) return <Message kind="error">{err}</Message>
  if (!rows) return <Skeleton rows={2} />
  const shown = engagementId ? rows.filter((r) => r.engagement_id === engagementId) : rows
  return (
    <Panel title={t('firewall_title')} id="firewall">
      {shown.length === 0 && <p className="muted">{t('common.none', { ns: 'translation' })}</p>}
      {shown.map((r) => {
        const conflict = r.result === 'conflict_found'
        return (
          <div key={r.id} className="card" style={{ marginBottom: 12 }}>
            <div><bdi dir="ltr" className="ident">{r.engagement_id}</bdi> {r.firm && <span>· <bdi>{r.firm}</bdi></span>}</div>
            <p>
              <Chip tone={conflict ? 'critical' : 'ok'}>{conflict ? t('firewall_conflict') : t('firewall_no_conflict')}</Chip>
              {r.status === 'suspended' && <> <Chip tone="urgent">{t('firewall_suspended')}</Chip></>}
            </p>
            <p>{r.independence_declared_at ? <Chip tone="ok">{t('firewall_declared')}</Chip> : <Chip tone="attention">{t('firewall_declaration_required')}</Chip>}</p>
            {r.manual_conflict_flags > 0 && <p><Chip tone="critical">{t('firewall_flags', { n: r.manual_conflict_flags })}</Chip></p>}
            <p className="muted">{t('firewall_rule')}: <bdi dir="ltr">{r.rule_version}</bdi> · {formatDateTime(r.evaluated_at, i18n.language)}</p>
            <p className="helper">{t('firewall_note')}</p>
          </div>
        )
      })}
    </Panel>
  )
}
