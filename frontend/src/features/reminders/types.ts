export type Bi = { en: string; ar: string }
export interface ReminderRow { reminder_id: string; channel: string; kind: string; language: string; deadline_category: string; planned_date: string; status: string; flags: string[]; inbox_state: string; body: { en: string | null; ar: string | null }; sent_at: string | null; due_date: string | null; is_demo: boolean }
export interface Prefs {
  language: 'ar' | 'en' | null
  channels: { portal: boolean; email: boolean; sms: boolean; whatsapp: boolean }
  sms_opt_in_at: string | null
  contacts: { email: string | null; email_verified: boolean; email_state: string; mobile: string | null; mobile_verified: boolean }
  channel_states: Record<string, { enabled: boolean; reason: string | null; mandatory: boolean }>
  role: 'owner' | 'delegate'
  lead_times: Record<string, number[]>
  send_window: { start: string; end: string }
}
export interface Inbox { items: ReminderRow[]; unread: number; held_notices: { reminder_id: string; text: Bi }[]; upcoming: ReminderRow[]; preferences: Prefs }
