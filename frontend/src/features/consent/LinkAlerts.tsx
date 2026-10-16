import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Message } from '../../components/ui'
import { get } from '../../lib/api'
import { useLinks } from './LinkStatusList'
import type { ConsentList } from './types'

/** SC3 alert strip entry: failed / withdrawn / stale links, expired or paused consents, statement update due. */
export default function LinkAlerts() {
  const { t } = useTranslation('consent')
  const nav = useNavigate()
  const { companyId, can } = useAuth()
  const { data } = useLinks(companyId)
  const [consents, setConsents] = useState<ConsentList | null>(null)
  useEffect(() => {
    if (!companyId || !can('consent.view', companyId)) return
    get<ConsentList>(`/api/companies/${companyId}/consents`).then(setConsents).catch(() => setConsents(null))
  }, [companyId, can])
  if (!data) return null
  const attention = data.rows.filter((r) => data.needs_attention.includes(r.link_id))
  const expired = consents?.consents.some((c) => c.status === 'expired' && !consents.consents.some((o) => o.status === 'active' && o.consent_type === c.consent_type))
  const paused = consents?.consents.some((c) => c.status === 'paused')
  const due = data.manual_uploads_line.badge === 'update_due'
  if (!attention.length && !expired && !paused && !due) return null
  return (
    <Message kind="warning" id="link-alerts">
      <div className="link-alerts-text">
        {attention.length > 0 && <div>{t('alert_failed', { n: attention.length, names: attention.map((r) => r.source_name).join(', ') })}</div>}
        {expired && <div>{t('alert_expired')}</div>}
        {paused && <div>{t('alert_paused')}</div>}
        {due && <div>{t('alert_upload_due', { n: data.manual_uploads_line.manual_data_age_days ?? 0 })}</div>}
      </div>
      <div className="actions">
        {can('consent.view', companyId) && <Button variant="secondary" onClick={() => nav('/consent')}>{t('open_centre')}</Button>}
        {due && can('uploads.manage', companyId) && <Button variant="secondary" onClick={() => nav('/settings?tab=data-links')}>{t('btn.upload_files')}</Button>}
      </div>
    </Message>
  )
}
