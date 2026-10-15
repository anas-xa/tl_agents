import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Chip, Panel, Skeleton } from '../../components/ui'
import { get } from '../../lib/api'
import { daysLeftLabel, formatAED } from '../../lib/format'
import { ctPeriods, lastClosedQuarter, type CalcView, type PackSummary } from './types'

interface Timing { last_check: { missing_items: { key: string }[] } | null }

/** SC3 'Tax' status card: VAT and corporate-tax state, days left (placeholder until the due date is confirmed) and what is missing. */
export default function DashboardPanel() {
  const { t, i18n } = useTranslation('tax')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const { companyId } = useAuth()
  const vatPeriod = lastClosedQuarter()
  const ctPeriod = ctPeriods()[1]
  const [vat, setVat] = useState<CalcView | null>(null)
  const [ct, setCt] = useState<CalcView | null>(null)
  const [missing, setMissing] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  const [filed, setFiled] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (!companyId) return
    const base = `/api/companies/${companyId}`
    get<CalcView>(`${base}/tax/vat/${vatPeriod}`).then(setVat).catch(() => setFailed(true))
    get<CalcView>(`${base}/tax/ct/${ctPeriod}`).then(setCt).catch(() => setFailed(true))
    // A return the owner has recorded as filed is shown as filed, never as overdue.
    get<{ packs: PackSummary[] }>(`${base}/drafts`)
      .then((r) => setFiled(new Set(r.packs.filter((p) => !p.superseded && p.review_status === 'filed_user_confirmed').map((p) => `${p.tax_type}:${p.period_id}`))))
      .catch(() => setFiled(new Set()))
    get<Timing>(`${base}/transactions/timing/vat/${vatPeriod}`).then((r) => setMissing(r.last_check ? r.last_check.missing_items.length : null)).catch(() => setMissing(null))
  }, [companyId, vatPeriod, ctPeriod])

  const row = (label: string, v: CalcView | null) => {
    if (!v) return <Skeleton rows={1} />
    const c = v.calculation
    if (!c) return <li>{label}: <Chip tone="neutral">{t('panel_no_calc')}</Chip></li>
    const days = c.due_date ? Math.round((new Date(c.due_date + 'T00:00:00').getTime() - Date.now()) / 86400000) : null
    const key = c.tax_type === 'vat' ? 'net_vat_fils' : 'tax_fils'
    const figure = c.outputs && c.state === 'current' && typeof c.outputs[key] === 'number' ? (c.outputs[key] as number) : c.net_figure_fils ?? null
    return (
      <li>
        {label}: <Chip tone={c.state === 'current' ? 'ok' : c.state === 'blocked' ? 'info' : 'attention'}>{t(`state_${c.state}`)}</Chip>
        {figure !== null && <> · <bdi dir="ltr">{formatAED(figure, lang)}</bdi></>}
        <div className="hint">
          {filed.has(`${c.tax_type}:${c.period_id}`) ? <Chip tone="ok">{t('st_filed_user_confirmed')}</Chip> : days !== null ? daysLeftLabel(days, lang) : t('days_left_placeholder')}
        </div>
      </li>
    )
  }

  return (
    <Panel title={t('panel_title')} actions={<Link to="/tax">{t('panel_open')}</Link>}>
      {failed ? <p className="hint">{t('generic_error')}</p> : (
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {row(t('panel_vat', { period: vatPeriod }), vat)}
          {row(t('panel_ct', { period: ctPeriod }), ct)}
        </ul>
      )}
      {missing !== null && missing > 0 && <p><Chip tone="attention">{t('panel_missing', { n: missing })}</Chip></p>}
      <p className="hint">{t('draft_label')}</p>
    </Panel>
  )
}
