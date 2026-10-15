import { useCallback, useEffect, useState } from 'react'
import { ApiError, get } from '../../lib/api'

export interface Bilabel { code: string; en: string; ar: string; k4?: boolean }
export interface Param { value: unknown; status: string; confirmed: boolean; label: string }
export interface CaseRow { id: string; action: 'opt_out' | 'refund'; state: string; chip: string; status_text: string; reason_code: string; reference_code: string; received_at: string; effective_at: string | null; can_cancel: boolean }
export interface Billing { id: string; status: string; hold_reason: string | null; collection_status: string; payment_reference: string | null; invoice_date: string | null; provisional: boolean; net_fils?: number; vat_fils?: number; gross_fils?: number; collected_fils?: number; outstanding_fils?: number; refunded_fils?: number }
export interface Fee { base_annual_fils: number; net_fils: number; vat_rate_bp: number; vat_fils: number; gross_fils: number; label: 'example' | 'confirmed'; vat_label: string; monthly_display_fils: number }
export interface Sub {
  id: string; licence_number: string; enrolment_basis: 'default_on' | 'opted_in'; cohort_id: string; start_date: string; end_date: string; status: string; badge: string
  example_mode: boolean; fee_schedule_version: string; opt_out_refund_config_version: string | null; service_mode: 'full' | 'read_only'; grace_until: string | null
  ended_on: string | null; ended_cause: string | null; opt_out_state: string; is_demo: boolean; fee: Fee | null; billing: Billing | null
  payments: { status?: string; amount_fils: number | null; basis: string | null; provisional: boolean; kind: string }[]; cases: CaseRow[]
}
export interface PilotRow { pilot_status: string; interest_status: string | null; enrolment_mode: string | null; cohort_name: string | null }
export interface LicenceRow { licence_number: string; licence_status: string; licence_expiry: string | null; pilot: PilotRow; empty_state: 'not_in_pilot' | 'opted_out' | 'in_cohort_no_event' | null; subscription: Sub | null; past: Sub[] }
export interface Complaint { id: string; reference: string; category: string; status: string; received_at: string; reply_by: string; licence_number: string | null; filed_for_owner: boolean }
export interface SubscriptionView {
  company_id: string; role: string; can_change: boolean; read_only_note: string | null; licences: LicenceRow[]; complaints: Complaint[]
  terms_version: string; notice_version: string; switches: Record<string, boolean>; parameters: Record<string, Param>
  reasons: { version?: string; opt_out?: Bilabel[]; refund?: Bilabel[] }; complaint_categories: Bilabel[]
  refund_response_time_working_days: number; included: Bilabel[]; not_included: Bilabel[]
}

/** Fetch with loading / error / slow (10 s) states; never guesses data on failure. */
export function useFetch<T>(url: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [loading, setLoading] = useState(false)
  const [slow, setSlow] = useState(false)
  const load = useCallback(async () => {
    if (!url) return
    setLoading(true)
    setSlow(false)
    const timer = setTimeout(() => setSlow(true), 10000)
    try {
      setData(await get<T>(url))
      setError(null)
    } catch (e) {
      setError(e as Error)
    } finally {
      clearTimeout(timer)
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps])
  useEffect(() => {
    load()
  }, [load])
  return { data, error, loading, slow, reload: load }
}

export function newRequestId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `req-${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
}

export function bl(item: Bilabel | undefined, lang: string): string {
  if (!item) return ''
  return lang.startsWith('ar') ? item.ar : item.en
}

export const BADGE_TONE: Record<string, 'ok' | 'attention' | 'info' | 'neutral' | 'critical' | 'draft'> = {
  pending_billing: 'attention', billing_requested: 'info', awaiting_det_confirmation: 'info', billed: 'info', active: 'ok',
  held_for_review: 'attention', ended: 'neutral', cancelled: 'neutral', opted_out: 'neutral', paused: 'attention',
}
export const BADGE_ICON: Record<string, string> = {
  pending_billing: '◔', billing_requested: '↗', awaiting_det_confirmation: '◷', billed: '▤', active: '✓', held_for_review: '⚑', ended: '■', cancelled: '✕', opted_out: '○', paused: '❚❚',
}
