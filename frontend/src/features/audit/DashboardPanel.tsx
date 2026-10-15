import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Chip, Panel, Skeleton } from '../../components/ui'
import { get } from '../../lib/api'
import type { AuditOverview } from './types'

/** SC3 'Audit' card: K20 indicator state (indicative, never a legal determination) and items for review. */
export default function DashboardPanel() {
  const { t, i18n } = useTranslation('audit')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { companyId } = useAuth()
  const [d, setD] = useState<AuditOverview | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    if (companyId) get<AuditOverview>(`/api/companies/${companyId}/audit`).then(setD).catch(() => setErr(true))
  }, [companyId])
  if (err) return <Panel title={t('dash.title')}><p>{t('error')}</p></Panel>
  if (!d) return <Panel title={t('dash.title')}><Skeleton rows={2} /></Panel>
  const text = d.flag.text[lang] || {}
  const open = (d.exceptions ?? []).filter((e) => e.status === 'New').length
  return (
    <Panel title={t('dash.title')} id="dash-audit">
      <p><Chip tone="info" icon="ⓘ">{text.badge_indicative}</Chip></p>
      <p><strong>{t(`indicator.states.${d.flag.state}`)}</strong></p>
      {d.exceptions && <p>{t('dash.exceptions', { n: open })}</p>}
      {d.working_file && <p className="muted">{d.working_file.status_label[lang]}</p>}
      <Link to="/audit">{t('dash.open')}</Link>
    </Panel>
  )
}
