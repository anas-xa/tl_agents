import { ApiError } from '../../lib/api'

export interface TxnRow {
  id: string
  txn_date: string
  description: string
  description_language: 'ar' | 'en' | 'mixed'
  counterparty: string | null
  direction: 'in' | 'out'
  aed_amount_fils: number
  original_amount_fils: number
  original_currency: string
  fx: { rate: number | null; source: string | null; rate_date: string | null; carried: boolean; missing: boolean } | null
  source_kind: string
  source_system: string
  source_id: string
  source_date: string
  manual_unverified: boolean
  treated_as_data: boolean
  consent_withdrawn: boolean
  status: 'proposed' | 'needs_review' | 'posted' | 'rejected' | 'quarantined' | 'draft_not_posted'
  review_reason: string | null
  proposed: { category: string | null; vat_code: string | null; vat_code_version: string | null; ledger_account: string | null }
  final: { category: string | null; vat_code: string | null; ledger_account: string | null }
  reviewer: { name: string; role: string; at: string } | null
  posted_at: string | null
  can_undo: boolean
  bulk_eligible: boolean
  quarantine: { made_by: string | null; access_removed_on: string | null } | null
}

export interface ConsentGate { allowed: boolean; state: string; ended_on?: string | null }

export interface TxnList {
  company_id: string
  role: string
  view: 'full' | 'summary' | 'read_only' | 'no_function'
  consent: { bank: ConsentGate; ledger: ConsentGate }
  counts: Record<string, number | string | boolean | null>
  rows: TxnRow[]
  can_decide_quarantine?: boolean
}

export interface Reference {
  categories: string[]
  vat_codes: { code: string; name_en: string; name_ar: string; gloss_en: string; gloss_ar: string; rate_percent: number; return_box_ref: string | null; status_label: string }[]
  accounts: { code: string; name_en: string; name_ar: string; reporting_line: string }[]
}

export interface RuleRef { rule_id: string; version: string; instrument: string | null; effective_from: string | null; status: string; label: string }

export interface ExcludedItem { classification_id: string; date: string; description: string; aed_amount_fils: number; reason: string }

export interface Calculation {
  id: string
  tax_type: 'vat' | 'ct'
  period_id: string
  period_start: string
  period_end: string
  version: number
  rule_version: string | null
  current_rule_version: string | null
  rule_refs: Record<string, RuleRef | null> | null
  ai_label: string
  review_status: 'not_reviewed' | 'reviewed'
  reviewed_by: { name: string; role: string; at: string } | null
  state: 'current' | 'incomplete' | 'stale' | 'no_rule_stop' | 'run_failed' | 'blocked' | 'missing_vat_code'
  state_reason: string | null
  label: string
  due_date: string | null
  due_date_source: string | null
  excluded_count: number
  excluded_total_fils: number
  excluded_items?: ExcludedItem[]
  notification_ref: string | null
  notification_sent_at: string | null
  created_at: string
  can_approve: boolean
  approval_disabled_reason: string | null
  outputs?: Record<string, unknown> | null
  trace?: Record<string, unknown>[]
  comparison?: { available: boolean; same?: boolean; difference_fils?: number; word?: string | null; used?: RuleRef; current?: RuleRef; figure_fils?: number; current_rules_figure_fils?: number }
  what_we_have?: { confirmed_transactions: number; needs_review: number }
  net_figure_fils?: number | null
  summary_note?: string
}

export interface CalcView {
  role: string
  can_prepare: boolean
  view_only_reason: string | null
  calculation: Calculation | null
  empty?: 'add_trn' | 'confirm_to_calculate'
  needs_review_count?: number
}

export interface Bi { en: string; ar: string }

export interface PackLine {
  key: string
  term: Bi
  gloss: Bi
  value_fils: number | null
  text: string | null
  line_class: 'calculated' | 'flagged' | 'person_entered'
  source_refs: Record<string, unknown>[]
  no_source: boolean
  no_source_reason: string | null
  return_box_ref: string | null
  accessible_name: string
  human_edited?: boolean
  held_for_specialist?: boolean
  sbr?: { indicator: string; text: string; reason: string | null; revenue_fils: number | null; revenue_source: string | null; cutoff_date: string | null; election_status: string; instrument: string; review_status: string }
}

export interface Pack {
  id: string
  company_id: string
  tax_type: 'vat' | 'ct'
  period_id: string
  version: number
  is_current: boolean
  current_version: number
  current_pack_id: string
  ai_label: Bi
  watermark: Bi
  emaratax_sentence: Bi
  product_name: Bi
  review_status: string
  review_status_label: Bi
  not_reviewed_by_human: boolean
  data_version: string
  rule_version: string | null
  assumptions: { text: string; citation: string }[]
  lines: PackLine[]
  sources: Record<string, unknown>[]
  basis: Record<string, unknown> | null
  human_edited: boolean
  last_human_change: { by: string | null; role: string | null; at: string | null }
  on_hold: boolean
  held: { delegate: string | null; changes: string[] | null } | null
  superseded: boolean
  what_changed: string | null
  locked: boolean
  no_source_count: number
  created_at: string
  is_demo: boolean
  can_approve: boolean
  approve_disabled_reason: string | null
  allowed_transitions: string[]
  history: { from: string | null; to: string; by: string | null; role: string | null; system: boolean; reason_code: string | null; at: string }[]
  versions: { id: string; version: number; review_status: string; superseded: boolean }[]
  role: string
}

export interface PackSummary { id: string; tax_type: 'vat' | 'ct'; period_id: string; version: number; review_status: string; review_status_label: Bi | null; superseded: boolean; on_hold: boolean; held_delegate: string | null; created_at: string; is_demo: boolean }

export interface ChecklistItem { key: string; mandatory: boolean; who: string; why: string; action: string; status: string; owner_only: boolean }

/** Map a backend refusal to a translated message key with interpolation values. */
export function errorKey(e: unknown): { key: string; values?: Record<string, unknown>; ref?: string } {
  if (e instanceof ApiError) {
    const d = (e.details || {}) as Record<string, unknown>
    switch (e.code) {
      case 'NO_FUNCTION': return { key: 'no_function' }
      case 'CONSENT_REQUIRED': return { key: 'awaiting_consent' }
      case 'REASON_REQUIRED': return { key: 'choose_reason' }
      case 'BASIS_REQUIRED': return { key: 'reason_no_basis' }
      case 'ROLE_CANNOT_SET_STATUS':
      case 'USE_APPROVALS':
      case 'SYSTEM_ONLY_STATUS': return { key: 'cannot_set_status', values: { role: String(d.role ?? '') } }
      case 'SELF_ACCEPT_REFUSED': return { key: 'self_accept' }
      case 'DATA_INCOMPLETE': return { key: 'missing_items', values: { n: Array.isArray(d.missing_items) ? d.missing_items.length : 0 } }
      case 'GENERATION_FAILED': return { key: 'could_not_prepare', values: { cause: String(d.cause ?? ''), step: String(d.next_step ?? '') } }
      case 'REMOTE_OWNER_NO_DRAFTS': return { key: 'remote_owner_no_access' }
      case 'NOT_YOUR_COMPANY': return { key: 'no_access_company_drafts' }
      case 'ON_HOLD_OWNER_ONLY': return { key: 'no_access_page' }
      case 'SUPERSEDED': return { key: 'approval_current_only' }
      case 'NOT_CURRENT': return { key: 'approval_off' }
      case 'ALREADY_DECIDED':
      case 'QUARANTINED': return { key: 'nothing_posted_until_decide' }
      case 'UNDO_WINDOW_CLOSED':
      case 'PERIOD_APPROVED':
      case 'NOTHING_TO_UNDO': return { key: 'undo_unavailable' }
      default: return { key: 'generic_error', ref: e.reference }
    }
  }
  return { key: 'generic_error' }
}

/** Quarter ids around today plus financial years, newest first. */
export function vatPeriods(today = new Date()): string[] {
  const out: string[] = []
  let y = today.getFullYear()
  let q = Math.floor(today.getMonth() / 3) + 1
  for (let i = 0; i < 6; i++) {
    out.push(`${y}-Q${q}`)
    q -= 1
    if (q === 0) { q = 4; y -= 1 }
  }
  return out
}

export function ctPeriods(today = new Date()): string[] {
  const y = today.getFullYear()
  return [`FY${y}`, `FY${y - 1}`, `FY${y - 2}`]
}

export function lastClosedQuarter(today = new Date()): string {
  return vatPeriods(today)[1]
}

/** Visually hidden live region (no shared class exists for it). */
export const SR_ONLY = { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' } as const
