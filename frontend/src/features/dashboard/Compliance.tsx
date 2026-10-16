import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { AiLabel, Button, Chip, Disclosure, Message } from '../../components/ui'
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
  // The Ejari gap is already explained by the banner above the cards; the card then shows only its status chip.
  const gapBanner = data.banners.some((b) => !b.page_level && b.kind === 'ejari_at_risk')
  return (
    <div id="compliance" className="dash-compliance">
      {data.banners.filter((b) => !b.page_level).map((b) => <Message key={b.kind} kind={b.kind === 'ejari_lapsed' ? 'error' : 'warning'}>{tx(b.text)}</Message>)}
      {s && <p className="dash-quiet">{data.all_clear ? <Chip tone="ok" icon="✓">{t('all_clear')}</Chip> : t('summary', { met: s.met, unverified: s.unverified, attention: s.attention, unknown: s.cannot_confirm })}</p>}
      <div aria-live="polite">
        {msg && (
          <Message kind={msg.kind}>
            {msg.text}{' '}
            {msg.ics && <a href={`data:text/calendar;charset=utf-8,${encodeURIComponent(ics(msg.ics.title, msg.ics.date))}`} download="qeonix-reminder.ics">{t('add_to_calendar')}</a>}
          </Message>
        )}
      </div>
      <ul className="dash-reqs">
        {data.cards.map((c) => {
          const ct = TONE[c.chip] ?? TONE.unknown
          const rc = c.reminder_control
          return (
            <li key={c.requirement_type} className="dash-req" aria-labelledby={`req-${c.requirement_type}`}>
              <div className="dash-req-row">
                <div className="dash-req-main">
                  <div className="dash-req-head">
                    <h3 id={`req-${c.requirement_type}`}>{tx(c.title)}</h3>
                    <Chip tone={ct.tone} icon={c.check_icon ? '✓' : ct.icon}>{tx(c.chip_label)}</Chip>
                  </div>
                  {c.due_date && (
                    <p className="dash-req-due">
                      <span className="nowrap">{t('due', { date: formatDate(c.due_date, i18n.language) })}</span>
                      {c.days_left !== null && c.days_left >= 0 && <span className="muted"> · {t('days_left_calendar', { n: c.days_left })}</span>}
                    </p>
                  )}
                  {c.gap_days !== null && c.gap_days > 0 && !gapBanner && <p className="dash-req-risk"><Chip tone="urgent" icon="!">{t('ejari_at_risk_short', { n: c.gap_days })}</Chip></p>}
                </div>
                <div className="dash-req-action">
                  {rc.state === 'available' && <Button variant="secondary" onClick={() => remind(c)}><Icon name="bell" size={16} />{c.status === 'overdue' ? t('remind_again_3') : t('remind_me')}</Button>}
                  {rc.state === 'text_link' && <Button variant="link" onClick={() => remind(c)}>{t('remind_me_check')}</Button>}
                  {rc.state === 'disabled' && <Button variant="secondary" aria-disabled="true" aria-describedby={`rr-${c.requirement_type}`} onClick={(e) => e.preventDefault()}>{t('remind_me')}</Button>}
                </div>
              </div>
              {rc.state === 'scheduled' && (
                <p className="dash-req-note">
                  <Icon name="bell" size={16} /> {t('reminder_set', { date: formatDate(rc.reminder_date, i18n.language), channel: rc.channel })}{' '}
                  <Button variant="link" onClick={() => rc.request_id && cancel(rc.request_id)}>{t('cancel')}</Button>
                </p>
              )}
              {rc.state === 'disabled' && <p id={`rr-${c.requirement_type}`} className="helper">{t('reminder_no_right')}</p>}
              {c.evidence === 'owner_declared' && (
                <div className="actions dash-req-actions">
                  <Button variant="secondary" disabled aria-disabled="true">{t('check_against_ejari')}</Button>
                  <Button variant="secondary" disabled aria-disabled="true">{t('upload_contract')}</Button>
                </div>
              )}
              <Disclosure summary={c.source_label ? t('details_source', { source: c.source_label }) : t('show_details')} className="dash-req-details">
                {c.source_line && <p>{tx(c.source_line)}</p>}
                {c.recommended_renew_by && c.recommended_renew_by !== c.due_date && <p>{t('recommended_renew_by')}: {formatDate(c.recommended_renew_by, i18n.language)}</p>}
                {c.notes.map((n, i) => <p key={i}>{tx(n)}</p>)}
                {c.holiday_note && <p><span aria-hidden="true">ⓘ </span>{tx(c.holiday_note.text)}</p>}
                <p className="muted">{tx(c.agent_note)}{c.last_confirmed ? ` · ${t('last_confirmed')} ${formatDate(c.last_confirmed, i18n.language)}` : ''}</p>
              </Disclosure>
            </li>
          )
        })}
      </ul>
      {data.to_be_confirmed.length > 0 && (
        <Disclosure summary={t('to_be_confirmed_title')}>
          <ul className="dash-tbc">{data.to_be_confirmed.map((r) => <li key={r.code}>{tx(r.title)} <Chip tone="info" icon="?">{tx(r.chip_label)}</Chip> <span className="helper">{tx(r.note)}</span></li>)}</ul>
        </Disclosure>
      )}
      {(data.drafts.length > 0 || canPrepare) && (
        <div className="dash-drafts">
          {data.drafts.map((d) => (
            <div key={d.id} className="dash-draft">
              <div className="dash-req-head">
                <strong>{i18n.language.startsWith('ar') ? d.content.ar?.title : d.content.en?.title}</strong>
                <AiLabel status={tx(d.status_label)} />
                {d.is_demo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}
              </div>
              <p className="helper">{tx(d.ai_label)} · {tx(d.footer)}</p>
              <div className="actions">
                {canPrepare && d.review_status === 'draft_not_reviewed' && <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs/${d.id}/review`)}>{t('mark_reviewed')}</Button>}
                {d.review_status !== 'approved_by_owner' && (canApprove && isOwner ? <Button onClick={() => act(`/api/companies/${companyId}/compliance/packs/${d.id}/approve`)}>{t('approve')}</Button> : <span className="helper">{t('only_owner_approve')}</span>)}
                {canPrepare && d.review_status !== 'approved_by_owner' && <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs/${d.id}/discard`)}>{t('discard')}</Button>}
              </div>
            </div>
          ))}
          {canPrepare && (
            <div className="actions dash-prepare">
              <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs`, { output_type: 'renewal_checklist' })}><Icon name="sparkle" size={16} />{t('prepare_pack')}</Button>
              <Button variant="secondary" onClick={() => act(`/api/companies/${companyId}/compliance/packs`, { output_type: 'document_pack' })}><Icon name="sparkle" size={16} />{t('prepare_docs')}</Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
