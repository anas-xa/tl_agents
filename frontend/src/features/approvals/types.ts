export type Bi = { en: string; ar: string }

export interface ApprovalRecord {
  approval_id: string
  request_id: string
  pack_id: string
  decision: 'approve' | 'reject' | 'request_changes'
  reason: string | null
  status: string
  status_reason: string | null
  approver_name: string
  assurance_level: string
  capacity: string
  display_role: string
  delegation_basis: { grant_id: string; granting_owner_name: string | null; start_date: string; end_date: string } | null
  authority_evidence_ref: string | null
  action_approved: string
  data_version_hash: string
  short_hash: string
  pack_version: number
  rule_version_ids: { rule_id: string | null; version: string | null }[] | null
  human_review_status: string | null
  informed_unreviewed_decision: boolean
  declaration_wording_version_id: string
  channel: string
  decided_at: string
  valid_until: string | null
  validity_days: number | null
  capped_at_due_date: boolean
  is_demo: boolean
}

export interface FilingStatus {
  state: 'not_filed' | 'filed_outside_self_declared' | 'filed_outside_values_differ' | 'authority_unavailable' | 'blocked'
  label: Bi
  banner: string
  note?: string
  record_id?: string
  filed_date?: string | null
  authority_reference?: string | null
  differences?: { key: string; term: Bi | null; prepared_fils: number | null; declared_fils: number }[] | null
  receipt?: { name: string; label: string } | null
  recorded_by?: string | null
  recorded_at?: string | null
  edited?: { at: string; by: string } | null
  submitted_by: string | null
  read_back: string
  acting_under_grant?: { delegate_name: string; granting_owner_name: string; grant_date: string } | null
}

export interface PackLine {
  key: string
  term: Bi
  value_fils: number | null
  text?: string | null
  line_class: string
  no_source?: boolean
}

export interface RequestRow {
  request_id: string
  company_id: string
  company_name: Bi | null
  pack_id: string
  submission_type: string
  return_type: 'vat' | 'ct'
  period_id: string
  period_start: string | null
  period_end: string | null
  due_date: string | null
  due_date_source: string | null
  amounts: { key: string; term: Bi | null; value_fils: number }[] | null
  rule_version: string | null
  human_review_status: string | null
  human_review_label: Bi | null
  not_reviewed_by_human: boolean
  draft_content_hash: string
  short_hash: string
  pack_version: number
  current_pack_hash: string | null
  authority_rule_type: string
  quorum_n: number
  status: 'open' | 'decided' | 'superseded' | 'expired' | 'blocked' | 'in_preparation'
  status_reason: string | null
  awaiting_owner: boolean
  requested_by: { name: string | null; role: string | null }
  created_at: string
  link_expires_at: string
  decided_at: string | null
  superseded_by: string | null
  escalation_case_id: string | null
  is_demo: boolean
  approval_valid: boolean
  approved_by: ApprovalRecord | null
  joint_collected: number
  history: ApprovalRecord[]
  filing: FilingStatus
  entitled_owner: string | null
  entitlement?: { allowed: boolean; reason_code: string | null }
  uaepass_failures?: number
}

export interface RequestDetail extends RequestRow {
  role: string
  flow_enabled: boolean
  phase_b_on: boolean
  validity_days: number
  pack?: { id: string; version: number; review_status: string; lines: PackLine[]; basis: Record<string, unknown> | null; sources_count: number; superseded: boolean; on_hold: boolean }
  fixtures: Fixture[]
}

export interface Fixture {
  state: string
  tag: string
  label: string
  banner: string
  caution?: string
  actions: string[]
}

export interface HistoryRow {
  request_id: string
  return_type: 'vat' | 'ct'
  period_id: string
  status_chip: 'approved' | 'waiting' | 'not_approved' | 'expired'
  request_status: string
  approved_by: { name: string; role: string; delegation_basis: ApprovalRecord['delegation_basis'] } | null
  decided_at: string | null
  data_version: { prepared_on: string; version: number; short_hash: string }
  submission_status: FilingStatus['state']
  submission_label: Bi
  submitted_by: string | null
  needs_attention: string | null
  is_demo: boolean
}

export interface ListResponse {
  role: string
  flow_enabled: boolean
  phase_b_on: boolean
  can_send: boolean
  requests: RequestRow[]
  awaiting: RequestRow[]
  history: HistoryRow[]
  packs_ready: { pack_id: string; tax_type: 'vat' | 'ct'; period_id: string; version: number; review_status: string; not_reviewed_by_human: boolean; is_demo: boolean }[]
}

export interface Grant {
  grant_id: string
  delegate_uuid: string
  delegate_name: string | null
  granting_owner_name: string | null
  authority_basis: string | null
  scope_option: 'single_return' | 'time_period'
  scope_items: { submission_type: string; tax_type: string; period_id: string | null }[]
  max_amount_fils: number | null
  start_date: string
  end_date: string
  status: 'active' | 'suspended' | 'expired' | 'revoked'
  created_at: string
}

export interface GrantsResponse {
  role: string
  phase_b_on: boolean
  locked: boolean
  grants: Grant[]
  delegates: { identity_uuid: string; name: string | null; chip: string; end_date: string | null }[]
  defaults: { start_date: string; end_date: string; max_end_date: string; max_days: number; default_days: number; scope_option: string } | null
  det_data: { stale: boolean; refreshed_at: string | null }
}

export interface Kpi23 {
  value_pct: number | null
  display: string
  status: 'no_data' | 'pass' | 'breach'
  numerator: number
  denominator: number
  breach_count: number
  self_reported_count: number
  release_approvals: number
  blocked_attempts: number
}

export interface Kpi24 {
  display: string
  mean_hours: number | null
  decided_count: number
  undecided_count: number
  breakdown: Record<string, number | null>
  by_document_type: Record<string, number | null>
  target_hours: number | null
}

export interface ComplianceView {
  k23: Kpi23
  k24: Kpi24
  submissions: { submission_ref: string; kind: string; company_id: string; tax_type: string | null; at: string; approval_id: string | null; match_status: 'valid' | 'exception'; exception_reason: string | null; severity: number | null; self_reported: boolean }[]
  blocked_attempts: { gate_id: string; path: string; reason_code: string | null; caller_type: string; tax_type: string | null; at: string }[]
  exceptions: { exception_id: string; submission_ref: string; reason_code: string; reason_label: Bi; severity: number; case_owner_role: string; review_status: string; created_at: string }[]
  job: { last_success_at: string | null; stale: boolean }
  flow_enabled: boolean
  wave_exit_blocked: boolean
  can_retry: boolean
}
