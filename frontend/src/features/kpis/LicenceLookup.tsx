import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { Button, Chip, Field, Ident, Message, Panel } from '../../components/ui'
import '../det/det.css'
import { ApiError, get } from '../../lib/api'
import { formatDate } from '../../lib/format'
import { useLang } from './parts'

const FIELDS = ['licence_number', 'trade_name_en', 'trade_name_ar', 'issuing_authority', 'licence_status', 'issue_date', 'expiry_date', 'subscription_status', 'billing_status', 'collection_status', 'enrolment_mode', 'subscription_start', 'subscription_end', 'cohort', 'wave', 'open_support_cases'] as const
type LicenceView = Record<(typeof FIELDS)[number] | 'subscription_badge', string | number | null>

/**
 * DET per-licence operational view (E9-S1 §2.13): exact lookup by licence number, allowed fields only.
 * Never usage, tax, deadline or filing status, escalation or survey reasons, document names, bank or financial data.
 * Every view is logged on the server and visible to the compliance reviewer.
 */
export default function LicenceLookup() {
  const { t } = useTranslation('kpis')
  const { lang } = useLang()
  const [number, setNumber] = useState('')
  const [view, setView] = useState<LicenceView | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const lookup = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!number.trim()) return
    setBusy(true)
    setErr(null)
    setView(null)
    try {
      const out = await get<{ licence: LicenceView }>(`/api/det/licences/${encodeURIComponent(number.trim())}`)
      setView(out.licence)
    } catch (ex) {
      setErr(ex instanceof ApiError && ex.status === 404 ? t('lookup_not_found') : ex instanceof ApiError && ex.status === 403 ? t('lookup_no_access') : t('error_all'))
    } finally {
      setBusy(false)
    }
  }
  const val = (k: (typeof FIELDS)[number]) => {
    const v = view?.[k]
    if (v === null || v === undefined || v === '') return '—'
    if (k.endsWith('_date') || k === 'subscription_start' || k === 'subscription_end') return formatDate(String(v), lang)
    if (k === 'licence_number') return <Ident>{v}</Ident>
    if (k === 'trade_name_ar') return <bdi dir="rtl">{v}</bdi>
    if (k === 'trade_name_en') return <bdi dir="ltr">{v}</bdi>
    if (k === 'enrolment_mode') return t(`val.${v}`, { defaultValue: String(v) })
    return <bdi>{String(v)}</bdi>
  }
  return (
    <Panel title={t('lookup_title')} id="det-licence-lookup">
      <p className="det-note"><Icon name="lock" size={16} />{t('lookup_intro')}</p>
      <form className="det-form-row" role="search" onSubmit={lookup}>
        <Field label={t('lookup_label')} id="lookup-number">
          <input id="lookup-number" dir="ltr" value={number} maxLength={40} onChange={(e) => setNumber(e.target.value)} autoComplete="off" />
        </Field>
        <Button type="submit" disabled={busy || !number.trim()}><Icon name="search" size={18} />{t('lookup_search')}</Button>
      </form>
      {err && <Message kind="warning">{err}</Message>}
      {view && (
        <div style={{ marginTop: 16 }}>
          <dl className="det-facts det-lookup-facts">
            {FIELDS.map((k) => (
              <div key={k}>
                <dt>{t(`f.${k}`)}</dt>
                <dd>{val(k)}</dd>
              </div>
            ))}
          </dl>
          <p role="status"><Chip tone="info" icon="👁">{t('lookup_logged')}</Chip></p>
        </div>
      )}
    </Panel>
  )
}
