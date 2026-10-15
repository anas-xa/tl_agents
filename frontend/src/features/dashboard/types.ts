import type { Bi, Obligation } from '../deadlines/lib'

export interface PanelData {
  panel: 'tax_status' | 'audit_status' | 'deadlines' | 'documents' | 'compliance'
  title: Bi
  source?: string
  last_updated?: string | null
  last_updated_dubai?: string | null
  freshness_state: 'fresh' | 'last_known' | 'cannot_be_confirmed' | 'not_available' | 'could_not_be_loaded' | 'not_linked_yet' | 'not_shared'
  stale_flag?: boolean
  reason_code?: string
  message?: Bi
  retry?: boolean
  last_good_time?: string
  request_access?: { state: 'available' | 'sent'; sent_at?: string }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data?: any
}

export interface Step { kind: string; title: Bi; ai_prepared: boolean; status_label?: Bi; link?: string | null; items?: { code: string; label_en: string; label_ar: string }[]; due_date?: string | null }
export interface AlertRow { kind: string; severity: string; text: Bi; link?: string | null }

export interface ApprovalCard { card_id: string; state: 'waiting' | 'approved' | 'declined' | 'expired'; text: Bi; what: Bi; prepared_by: Bi; approve_by?: string; decided_at?: string; expires_at?: string; approver?: string; actions: string[]; is_demo: boolean }

export interface Dashboard {
  company: { company_id: string; trade_name_en: string; trade_name_ar: string; licence_number: string | null; licence_status: string | null; licence_expiry: string | null }
  panel_order: string[]
  panels: PanelData[]
  next_steps: Step[]
  alerts: AlertRow[]
  licence_banner: { kind: string; text: Bi; disabled_actions: string[]; available_actions: string[] } | null
  acting_as: { role: 'owner' | 'delegate'; company_role: string; person: string; principal: string | null; owner_abroad: boolean; label: Bi; held_functions: string[]; owner_only_functions: string[]; accessible_name: string }
  not_shared_note: Bi | null
  view: 'owner' | 'delegate' | 'remote_owner'
  k10_tile: Bi
  remote?: { allowed_areas: string[]; remote_services_agent_enabled: boolean; freshness_banner: { last_update: string | null; sources_not_current: number }; approval_cards: ApprovalCard[]; approvals_empty: Bi; generic_denial: Bi }
}

export type MiniObligation = Pick<Obligation, 'obligation_id' | 'obligation_type' | 'subtype' | 'name' | 'due_date' | 'date_status' | 'days_left' | 'days_left_tier' | 'status_chip' | 'status_chips' | 'readiness' | 'readiness_label' | 'missing_items' | 'is_stated' | 'calculated' | 'draft_pack_id' | 'date_updated' | 'recommended_submit_by' | 'provisional_date' | 'is_demo'>
