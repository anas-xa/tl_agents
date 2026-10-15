import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { AiLabel, Button, Chip, Message } from '../../components/ui'
import { ApiError, del, post } from '../../lib/api'
import { formatDate } from '../../lib/format'
import { useBi, type Bi } from '../deadlines/lib'

interface Card {
  requirement_type: string
  title: Bi
  status: string
  chip: string
  chip_label: Bi
  evidence: string
  source_label: string | null
  source_line: Bi | null
  due_date: string | null
  days_left: number | null
  recommended_renew_by: string | null
  gap_days: number | null
  notes: Bi[]
  rule_version: string | null
  last_confirmed: string | null
  agent_note: Bi
  holiday_note: { kind: string; text: Bi } | null
  reminder_control: { state: string; request_id?: string; reminder_date?: string; channel?: string; reason?: Bi }
  check_icon: boolean
}
interface Draft { id: string; output_type: string; review_status: string; status_label: Bi; ai_label: Bi; footer: Bi; content: { en: { title: string } | null; ar: { title: string } | null }; is_demo: boolean }
export interface ComplianceData {
  empty: boolean
  empty_message?: Bi
  cards: Card[]
  to_be_confirmed: { code: string; title: Bi; chip_label: Bi; note: Bi; approving_authority: string }[]
  summary: { met: number; unverified: number; attention: number; cannot_confirm: number } | null
  banners: { kind: string; text: Bi; page_level?: boolean }[]
  all_clear: boolean
  drafts: Draft[]
}

const TONE: Record<string, { tone: 'ok' | 'attention' | 'urgent' | 'critical' | 'info' | 'neutral'; icon: string }> = {
  met: { tone: 'ok', icon: '✓' },
  owner_declared: { tone: 'neutral', icon: '👤' },
  due_soon: { tone: 'attention', icon: '◔' },
  at_risk: { tone: 'urgent', icon: '!' },
  overdue: { tone: 'critical', icon: '✕' },
  unknown: { tone: 'info', icon: '?' },
}

function ics(title: string, date: string): string {
  const d = date.replace(/-/g, '')
  return `BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Qeonix//Reminders//EN\r\nBEGIN:VEVENT\r\nUID:${d}-${title.replace(/\W/g, '')}@qeonix\r\nDTSTART;VALUE=DATE:${d}\r\nSUMMARY:${title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n`
}

/** SC3 'Licence requirements' card group (E3-S3). Only Met shows a check icon; owner-declared values never show 'Met'. */
export default function Compliance({ data, onChange, canPrepare, canApprove, isOwner }: { data: ComplianceData; onChange: () => void; canPrepare: boolean; canApprove: boolean; isOwner: boolean }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const { companyId } = useAuth()
  const [msg, setMsg] = useState<{ kind: 'success' | 'error' | 'info'; text: string; ics?: { title: string; date: string } } | null>(null)
  if (data.empty) return <p>{tx(data.empty_message)}</p>
  const remind = async (c: Card) => {
    try {
      const out = await post<{ reminder_date: string; channel: string }>(`/api/companies/${companyId}/reminders/requests`, { requirement_type: c.requirement_type, due_date: c.due_date })
      setMsg({ kind: 'success', text: t('reminder_set', { date: formatDate(out.reminder_date, i18n.language), channel: out.channel }) })
      onChange()
    } catch (e) {
      const noRight = e instanceof ApiError && e.code === 'REMINDER_RIGHT_OFF'
      setMsg({ kind: 'error', text: noRight ? t('reminder_no_right') : t('reminder_failed'), ics: c.due_date ? { title: tx(c.title), date: c.due_date } : undefined })
    }
  }
  const cancel = async (id: string) => {
    await del(`/api/companies/${companyId}/reminders/requests/${id}`)
    setMsg({ kind: 'info', text: t('reminder_cancelled') })
    onChange()
  }
  const act = async (path: string, body: unknown = {}) => {
    try {
      await post(path, body)
      onChange()
    } catch (e) {
      setMsg({ kind: 'error', text: e instanceof ApiError && e.code === 'APPROVAL_NOT_PERMITTED' ? t('only_owner_approve') : (e as Error).message })
    }
  }
  const s = data.summary
  return (
    <div id="compliance">
      {data.banners.filter((b) => !b.page_level).map((b) => <Message key={b.kind} kind={b.kind === 'ejari_lapsed' ? 'error' : 'warning'}>{tx(b.text)}</Message>)}
      {s && <p className="helper">{data.all_clear ? `✓ ${t('all_clear')}` : t('summary', { met: s.met, unverified: s.unverified, attention: s.attention, unknown: s.cannot_confirm })}</p>}
      <div aria-live="polite" style={{ minHeight: msg ? undefined : 0 }}>
        {msg && (
          <Message kind={msg.kind}>
            {msg.text}{' '}
            {msg.ics && <a href={`data:text/calendar;charset=utf-8,${encodeURIComponent(ics(msg.ics.title, msg.ics.date))}`} download="qeonix-reminder.ics">{t('add_to_calendar')}</a>}
          </Message>
        )}
      </div>
      <div className="grid">
        {data.cards.map((c) => {
          const ct = TONE[c.chip] ?? TONE.unknown
          const rc = c.reminder_control
          return (
            <section key={c.requirement_type} className="card" aria-labelledby={`req-${c.requirement_type}`}>
              <h3 id={`req-${c.requirement_type}`} style={{ marginTop: 0 }}>{tx(c.title)}</h3>
              <p>
                <Chip tone={ct.tone} icon={c.check_icon ? '✓' : ct.icon}>{tx(c.chip_label)}</Chip>{' '}
                {c.source_label && <Chip tone="info" icon="⚑">{c.source_label}</Chip>}
              </p>
              {c.source_line && <p className="helper">{tx(c.source_line)}</p>}
              {c.due_date && <p>{t('due', { date: formatDate(c.due_date, i18n.language) })} · {c.days_left !== null && c.days_left >= 0 ? t('days_left_calendar', { n: c.days_left }) : null}</p>}
              {c.recommended_renew_by && c.recommended_renew_by !== c.due_date && <p className="helper">{t('recommended_renew_by')}: {formatDate(c.recommended_renew_by, i18n.language)}</p>}
              {c.gap_days !== null && c.gap_days > 0 && <p><Chip tone="urgent" icon="!">{t('ejari_at_risk_short', { n: c.gap_days })}</Chip></p>}
              {c.notes.map((n, i) => <p key={i} className="helper">{tx(n)}</p>)}
              {c.holiday_note && <p className="helper"><span aria-hidden="true">ⓘ </span>{tx(c.holiday_note.text)}</p>}
              <p className="helper">{tx(c.agent_note)}{c.last_confirmed ? ` · ${t('last_confirmed')} ${formatDate(c.last_confirmed, i18n.language)}` : ''}</p>
              {c.evidence === 'owner_declared' && (
                <div className="actions">
                  <Button variant="secondary" disabled aria-disabled="true">{t('check_against_ejari')}</Button>
                  <Button variant="secondary" disabled aria-disabled="true">{t('upload_contract')}</Button>
                </div>
              )}
              {rc.state === 'available' && <Button variant="secondary" onClick={() => remind(c)}>🔔 {c.status === 'overdue' ? t('remind_again_3') : t('remind_me')}</Button>}
              {rc.state === 'text_link' && <Button variant="link" onClick={() => remind(c)}>{t('remind_me_check')}</Button>}
              {rc.state === 'scheduled' && (
                <p>
                  🔔 {t('reminder_set', { date: formatDate(rc.reminder_date, i18n.language), channel: rc.channel })}{' '}
                  <Button variant="link" onClick={() => rc.request_id && cancel(rc.request_id)}>{t('cancel')}</Button>
                </p>
              )}
              {rc.state === 'disabled' && (
                <p>
                  <Button variant="secondary" aria-disabled="true" aria-describedby={`rr-${c.requirement_type}`} onClick={(e) => e.preventDefault()}>{t('remind_me')}</Button>
                  <span id={`rr-${c.requirement_type}`} className="helper"> {t('reminder_no_right')}</span>
                </p>
              )}
            </section>
          )
        })}
      </div>
      {data.to_be_confirmed.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary>{t('to_be_confirmed_title')}</summary>
          <ul>{data.to_be_confirmed.map((r) => <li key={r.code}>{tx(r.title)} <Chip tone="info" icon="?">{tx(r.chip_label)}</Chip> <span className="helper">{tx(r.note)}</span></li>)}</ul>
        </details>
      )}
      <div style={{ marginTop: 12 }}>
        {data.drafts.map((d) => (
          <div key={d.id} className="card" style={{ marginBottom: 8 }}>
            <strong>{i18n.language.startsWith('ar') ? d.content.ar?.title : d.content.en?.title}</strong> <AiLabel status={tx(d.status_label)} /> {d.is_demo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}
            <p className="helper">{tx(d.ai_label)} · {tx(d.footer)}</p>
            <div className="actions">
              {canPrepare && d.review_status === 'draft_not_reviewed' && <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs/${d.id}/review`)}>{t('mark_reviewed')}</Button>}
              {d.review_status !== 'approved_by_owner' && (canApprove && isOwner ? <Button onClick={() => act(`/api/companies/${companyId}/compliance/packs/${d.id}/approve`)}>{t('approve')}</Button> : <span className="helper">{t('only_owner_approve')}</span>)}
              {canPrepare && d.review_status !== 'approved_by_owner' && <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs/${d.id}/discard`)}>{t('discard')}</Button>}
            </div>
          </div>
        ))}
        {canPrepare && (
          <div className="actions">
            <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs`, { output_type: 'renewal_checklist' })}>✎ {t('prepare_pack')}</Button>
            <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs`, { output_type: 'document_pack' })}>✎ {t('prepare_docs')}</Button>
          </div>
        )}
      </div>
    </div>
  )
}
