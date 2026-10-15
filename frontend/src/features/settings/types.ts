export type Toggle = 'view_dashboard' | 'prepare_data' | 'grant_bank_consent' | 'approve_submissions' | 'change_subscription'
export const PHASE_A: Toggle[] = ['view_dashboard', 'prepare_data']
export const PHASE_B: Toggle[] = ['grant_bank_consent', 'approve_submissions', 'change_subscription']

export interface Person {
  kind: 'role' | 'invitation'
  id: string
  identity_uuid: string | null
  display_name: string | null
  role: string
  status: string
  chip: 'pending' | 'active' | 'suspended' | 'removed'
  toggles: Toggle[]
  functions: string[]
  granted_at: string
  expires_at?: string
  name_differs: boolean
  dormant_flag: boolean
  authority_label: string | null
  reconfirm_by?: string | null
}

export interface Authority {
  det_refreshed_at: string | null
  stale: boolean
  no_det_record: boolean
  has_matchable_owner: boolean
  hold_state: 'none' | 'signatory_change_hold' | 'no_owner'
  hold_started_at: string | null
  det_operations_alerted_at: string | null
  reconfirm_by: string | null
}

export interface ToggleMeta { toggle: Toggle; phase: 'A' | 'B'; locked: boolean; default: boolean }

export interface Quarantined { id: string; draft_type: string; draft_ref: string; delegate_identity_uuid: string; delegate_name: string | null; touched_action: string; marker: string; status: string; quarantined_at: string; is_demo: boolean }

export interface Change { id: string; company_id: string; company_name_en: string | null; company_name_ar: string | null; change_type: string; delegate_label: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; reason: string | null; changed_by_name: string | null; changed_by_role: string | null; changed_at: string; acknowledged: boolean }

export interface OwnRights { company_id: string; toggles: Toggle[]; functions: string[]; status: string | null; hold_state: string; locked_toggles: Record<string, { locked: boolean }> }

export interface DelegatesResponse {
  company_id: string
  scope: 'all' | 'own'
  people: Person[]
  authority: Authority
  toggles: ToggleMeta[]
  limits: { max_delegates_per_company: number; max_companies_per_delegate: number; invitation_validity_days: number }
  statement: { en: string; ar: string }
  quarantine: Quarantined[]
  recent_changes: Change[]
  own: OwnRights | null
  last_updated: string
}
