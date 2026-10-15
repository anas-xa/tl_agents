export type Bi = { en: string; ar: string }

export interface Indicator {
  id?: string
  state: 'likely_required' | 'likely_not_required' | 'cannot_determine' | 'not_yet_assessed'
  reasons?: string[]
  cannot_determine_reasons?: string[]
  checklist?: { item: string; en: string; ar: string; gloss_en?: string; gloss_ar?: string }[]
  caveats?: string[]
  criteria_version?: string
  instrument?: string
  confirmation_state?: string
  period_start?: string | null
  period_end?: string | null
  period_months?: number | null
  revenue_source?: string | null
  governing_revenue_fils?: number | null
  twelve_month_equivalent_fils?: number | null
  near_threshold?: boolean
  evaluated_at?: string
  previous_result?: string | null
  change_notice?: boolean
  banner_hidden?: boolean
  not_refreshed?: boolean
  case?: { case_id: string; status?: string; opened_at?: string; owning_role?: string } | null
  is_demo?: boolean
  wording: { state: string; keys: string[] }
  text: { en: Record<string, string>; ar: Record<string, string> }
}

export interface FlagRow {
  id: string
  rule_id: string
  rule_version: string
  rule_version_at_flag: string
  rule_title: Bi | null
  rule_label: string | null
  period: string
  source: string
  severity: 'High' | 'Medium' | 'Low'
  status: 'New' | 'Confirmed' | 'Explained' | 'Dismissed' | 'Escalated'
  revision_no: number
  flagged_at: string
  evidence_changed_since: string | null
  source_withdrawn: boolean
  based_on_data_up_to: string | null
  ai_label: Bi
  amount_fils: number | null
  row_count: number
  is_demo: boolean
}

export interface EvidenceRow { record_id: string; record_version?: number; source?: string; date?: string; amount_fils?: number | null; counterparty?: string | null; invoice_number?: string | null; account_code?: string | null; masked?: boolean }

export interface FlagDetail extends FlagRow {
  evidence: EvidenceRow[]
  basis: Record<string, unknown> | null
  model_version: string
  revisions: { revision_no: number; created_at: string; actor: string; change_summary: string; rule_version: string; superseded_before_decision: boolean; evidence: EvidenceRow[] }[]
  decisions: { id: string; decision: string; reason: string; by: string; role: string; role_label: string | null; at: string; revision_no: number; superseded: boolean; quarantined: boolean }[]
}

export interface Gap { id: string; gap_number: number; item: Bi; why: Bi; who_can_fix: string; status: 'open' | 'requested' | 'received' | 'overdue'; action: string; assignee_name: string | null; due_date: string | null }

export interface WorkingFile {
  id: string
  period_start: string
  period_end: string
  version_no: number
  status: 'draft' | 'under_review' | 'signed' | 'rejected'
  status_label: Bi
  header: Bi
  completeness_state: 'incomplete' | 'complete' | 'complete_with_exceptions'
  sign_off_status: string
  out_of_date: boolean
  changed_on: string | null
  changed_by: string | null
  signature_void: boolean
  watermark: Bi
  page1_notice: Bi
  ai_prepared_content: { figures?: { key: string; label: Bi; value_fils: number | null; gap: number | null }[] }
  human_approved_content: Record<string, unknown> | null
  reviewer_name: string | null
  gaps: Gap[]
  gaps_summary: { complete: number; total: number }
  history: { who: string; role: string; at: string; from: string | null; to: string; invalid: boolean; invalid_since: string | null }[]
  engagement: { id: string; status: string; engagement_manager_role: string; preparing_team_role: string } | null
  return: { kind: string; reason_code: string; at: string; by_role: string; free_text: string | null; reason_language: string } | null
  review_recorded: { text: Bi; supplied_documents_only: boolean; supplied_documents_text: Bi | null } | null
  signed_outside: { text: Bi; badge: Bi } | null
  signing_available: boolean
  is_demo: boolean
}

export interface AuditOverview {
  role: string
  flag: Indicator
  can: Record<string, boolean>
  exceptions: FlagRow[] | null
  exceptions_hidden_reason?: Bi
  read_only_note?: Bi
  download_note?: Bi
  decide_disabled_reason?: Bi
  review?: { last_cycle_at: string | null; status: string | null; sources_read: string[]; more_available: boolean; empty_state: string | null; ended_on: string | null; bank_rules_visible: boolean }
  working_file: WorkingFile | null
  working_file_hidden?: Bi
  working_file_empty?: Bi
}
