/** Shapes returned by backend/app/modules/consent/api.py and backend/app/modules/datalinks/api.py. */

export interface TimelineStep { key: 'withdrawn' | 'pulls_stopped' | 'revoked_at_source'; state: 'done' | 'in_progress' | 'pending' | 'failed'; at: string | null; source?: string }
export interface Timeline {
  withdrawal_id: string
  withdrawn_at: string
  withdrawn_by: string | null
  provider_revocation_status: string
  pulls_stopped_at: string | null
  k13_class: string
  receipt_ref: string | null
  steps: TimelineStep[]
}

export interface ConsentRow {
  consent_id: string
  version: number
  consent_type: string
  source: string
  provider_name: string | null
  data_types: string[]
  data_types_not_read: string[]
  accounts_masked: string[]
  purpose: string
  recipient: string | null
  valid_from: string
  expires_at: string
  status: string
  display_status: string
  status_reason: string | null
  grantor_display_name: string | null
  grantor_role: string
  granting_owner_name: string | null
  delegation_id: string | null
  granted_by_removed_delegate: boolean
  granted_at: string
  withdrawn_at: string | null
  expired_at: string | null
  superseded_by: string | null
  receipt_ref: string | null
  is_demo: boolean
  days_left: number | null
  timeline: Timeline | null
  withdrawal_receipt?: { receipt_number: string; en: Record<string, unknown>; ar: Record<string, unknown> } | null
}

export interface Rights {
  role: string | null
  is_delegate: boolean
  is_remote_owner: boolean
  can_view: boolean
  can_grant: boolean
  can_withdraw: boolean
  can_upload: boolean
  can_request: boolean
  refusal_code: string | null
  step_up_required: string
  assurance_level: string
  tax_consent_online: boolean
}

export interface ConsentList {
  consents: ConsentRow[]
  rights: Rights
  consent_types: string[]
  controlled_lists: { version: number; purposes: string[]; data_types: Record<string, string[]> }
  wording_version: string
  retention: { classes: { class: string; record_type: string; period: string; legal_hold: boolean }[] }
  route: { route_holder: string; openfinance_enabled: boolean; max_duration_months_bank: number; max_duration_months: number }
  authority_rule: string
  loading_slow_threshold_seconds: number
}

export interface ReceiptOut {
  receipt_number: string
  kind: string
  en: { title: string; rows?: { label: string; value: string }[]; footer?: string; [k: string]: unknown }
  ar: { title: string; rows?: { label: string; value: string }[]; footer?: string; [k: string]: unknown }
}

export interface LinkRow {
  source_type: string
  source_name: string
  link_id: string
  badge: string
  last_successful_refresh_at: string | null
  freshness: { state: string; age_hours: number | null; reason: string | null }
  data_age_days: number | null
  next_step: string | null
  reason_line: string | null
  reference_id: string | null
  masked_account: string | null
  connecting_since: string | null
  still_connecting: boolean
  partial: { refreshed: number; total: number; missing: string[] } | null
  last_known: { status: string; at: string | null } | null
  excluded_from_k27: boolean
  is_demo: boolean
  manual_entries: { tax_type: string; entered_at: string | null; source: string }[]
}

export interface Bank { bank_id: string; name_en: string; name_ar: string; availability: string; demo: boolean }

export interface ErpLink {
  link_id: string
  system_type: string
  link_type: string
  status: string
  chip: 'connected' | 'importing' | 'needs_attention' | 'disconnected'
  created_by: string | null
  created_by_role: string | null
  created_at: string
  last_refreshed_at: string | null
  data_version: number
  runs: { run_id: string; result: string; failed_count: number; needs_mapping: string[]; data_version: number }[]
}

export interface LinksOut {
  rows: LinkRow[]
  manual_uploads_line: { count: number; latest_statement_end: string | null; manual_data_age_days: number | null; badge: string | null; state: string }
  needs_attention: string[]
  route: { route_holder: string; bank_link_allowed: boolean; openfinance_enabled: boolean }
  banks: Bank[]
  erp: { supported_systems: string[]; file_upload_enabled: boolean; accepted_export_types: string[]; preconditions: string[] }
  erp_links: ErpLink[]
  remote_owner_read_only: boolean
  can_manage: boolean
}

export interface Upload {
  upload_id: string
  kind: string
  export_type: string | null
  bank_name: string | null
  account_masked: string | null
  period_start: string | null
  period_end: string | null
  file_name: string
  uploaded_by: string | null
  uploader_role: string | null
  uploaded_at: string
  label: string
  rows_total: number
  rows_accepted: number
  rows_rejected: number
  rows_skipped_duplicate: number
  status: string
  rejection_cause: string | null
  quarantine_reason: string | null
  declaration_id: string | null
  purpose: string | null
  statement_age_badge: string | null
  data_as_of: string | null
  is_demo: boolean
}

export interface UploadsOut {
  uploads: Upload[]
  limits: { max_size_mb: number; max_rows: number; formats: string[]; notice_version: string; notice_en: string; notice_ar: string }
  manual_data_age: { manual_data_age_days: number | null; badge: string | null }
}

export interface TaxProfile {
  profile_id: string
  tax_type: 'vat' | 'corporate_tax'
  trn: string | null
  registration_status: string | null
  filing_status: string | null
  filing_frequency: string | null
  tax_period_start: string | null
  tax_period_end: string | null
  due_dates: { period_end: string | null; due_date: string; source: string }[]
  due_date_source: string
  small_business_relief: { period_end: string; indicator: string; source: string }[]
  source: string
  verification_tag: string
  entered_by: string | null
  entered_at: string | null
  as_of: string
  is_demo: boolean
}

export interface TaxLinkOut {
  status: string
  switch_on: boolean
  demo_data: boolean
  error_cause: string | null
  last_good_read_at: string | null
  remote_owner: boolean
  profiles: TaxProfile[]
}
