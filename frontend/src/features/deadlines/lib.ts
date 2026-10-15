import type React from 'react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, get } from '../../lib/api'

export type Bi = { en: string; ar: string }

export interface MissingItem { code: string; label_en: string; label_ar: string }

/** SC4 Obligation contract (E1-S3 Q357) as returned by /api/companies/{id}/obligations and /api/me/obligations. */
export interface Obligation {
  obligation_id: string
  company_id: string
  company_name: Bi | null
  licence_number: string | null
  obligation_type: 'licence_renewal' | 'vat_return' | 'ct_return' | 'audit' | 'ejari_renewal' | 'other'
  subtype: string | null
  name: Bi
  period_start: string | null
  period_end: string | null
  period_id: string | null
  due_date: string | null
  statutory_date: string | null
  date_used: string | null
  due_date_source: string
  deadline_source: string
  date_status: 'confirmed' | 'not_confirmed'
  is_stated: boolean
  calculated: boolean
  rule_version: string | null
  calendar_version: string | null
  calculation_time: string | null
  recommended_submit_by: string | null
  nonworking_flag: string
  readiness: 'not_started' | 'data_missing' | 'draft_ready' | 'owner_approved' | 'receipt_recorded'
  readiness_detail: string
  readiness_label: Bi
  draft_pack_id: string | null
  missing_items: MissingItem[]
  days_left: number | null
  days_left_tier: 'neutral' | 'attention' | 'urgent' | 'critical' | 'unknown'
  status_chip: string
  status_chips: string[]
  data_basis: string
  input_source: string
  source_chip: 'computed' | 'stated'
  filed_state: string | null
  done: boolean
  recalc_state: string
  last_confirmed_date: string | null
  provisional_date: string | null
  date_updated: { old_date: string; new_date: string | null; change_time: string; source_tag: string } | null
  notes: Bi[]
  updated_at: string
  is_demo: boolean
}

export interface CompanyView {
  company_id: string
  items: Obligation[]
  withheld_count: number
  withheld_note: Bi | null
  empty_state: { title: Bi; body: Bi; q395?: Bi; fields: string[]; field_label?: Bi; notify_owner?: boolean } | null
  pending: Bi | null
  rules_version: { version: string; checked: string | null; label: Bi }
  calendar_versions: string
  role: string
}

export interface PortfolioView {
  items: Obligation[]
  companies: { company_id: string; trade_name_en: string; trade_name_ar: string; withheld_count: number }[]
  withheld_count: number
  withheld_note: Bi | null
}

export function useBi() {
  const { i18n } = useTranslation()
  const lang: 'ar' | 'en' = i18n.language.startsWith('ar') ? 'ar' : 'en'
  return { lang, tx: (b: Bi | null | undefined) => (b ? b[lang] || b.en : '') }
}

/** Fetch with loading / error / retry; keeps the last good value while refreshing. */
export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [loading, setLoading] = useState(!!path)
  const [loadedAt, setLoadedAt] = useState<Date | null>(null)
  const load = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      setData(await get<T>(path))
      setError(null)
      setLoadedAt(new Date())
    } catch (e) {
      setError(e as Error)
    } finally {
      setLoading(false)
    }
  }, [path])
  useEffect(() => {
    load()
  }, [load])
  return { data, error, loading, loadedAt, reload: load, setData }
}

export function errorCode(e: Error | null): string | null {
  return e instanceof ApiError ? e.code : null
}

export const srOnly: React.CSSProperties = { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' }

/** Tier -> chip tone and icon (icon + text, never colour alone). */
export function tierTone(tier: string): { tone: 'neutral' | 'attention' | 'urgent' | 'critical' | 'info'; icon: string } {
  switch (tier) {
    case 'critical':
      return { tone: 'critical', icon: '✕' }
    case 'urgent':
      return { tone: 'urgent', icon: '!' }
    case 'attention':
      return { tone: 'attention', icon: '◔' }
    case 'unknown':
      return { tone: 'info', icon: '?' }
    default:
      return { tone: 'neutral', icon: '○' }
  }
}

/** Device offset from Dubai (UTC+4) in hours; 0 when the device is on Dubai time. Never stored. */
export function deviceOffsetFromDubai(): number {
  const deviceMinutes = -new Date().getTimezoneOffset()
  return (deviceMinutes - 240) / 60
}
