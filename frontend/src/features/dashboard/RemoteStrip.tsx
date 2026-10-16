import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Disclosure, Message, Panel } from '../../components/ui'
import { ApiError, post } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { deviceOffsetFromDubai, useBi } from '../deadlines/lib'
import type { ApprovalCard, Dashboard } from './types'

const STATE_CHIP: Record<ApprovalCard['state'], { tone: 'attention' | 'ok' | 'neutral' | 'critical'; icon: string }> = {
  waiting: { tone: 'attention', icon: '⌛' },
  approved: { tone: 'ok', icon: '✓' },
  declined: { tone: 'neutral', icon: '✕' },
  expired: { tone: 'critical', icon: '◷' },
}

/** Local time line (second zone) for owners abroad: one fixed instant, no countdown. */
function localLine(iso: string, lang: string, t: (k: string, o?: Record<string, unknown>) => string): string | null {
  const off = deviceOffsetFromDubai()
  if (off === 0) return null
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  const mins = -new Date().getTimezoneOffset()
  const sign = mins >= 0 ? '+' : '-'
  const hh = Math.floor(Math.abs(mins) / 60)
  const local = d.toLocaleString(lang === 'ar' ? 'ar-AE-u-nu-latn' : 'en-GB', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
  return t('your_time', { time: local, offset: `${sign}${hh}` })
}

/** E3-S5 freshness banner for the remote owner (shown with the page alerts). */
export function RemoteFreshness({ remote }: { remote: NonNullable<Dashboard['remote']> }) {
  const { t, i18n } = useTranslation('dashboard')
  const fb = remote.freshness_banner
  if (!fb.last_update) return null
  return <Message kind={fb.sources_not_current ? 'warning' : 'info'}>{t('freshness_banner', { time: formatDateTime(fb.last_update, i18n.language), n: fb.sources_not_current })}</Message>
}

/** E3-S5 remote-owner approvals: waiting requests first and prominent; decided and expired ones folded below
 * (all four states keep their full wording and actions). Demo data fixtures are labelled once in the header. */
export default function RemoteStrip({ remote, companyId, onChange }: { remote: NonNullable<Dashboard['remote']>; companyId: string; onChange: () => void }) {
  const { t } = useTranslation('dashboard')
  const { tx } = useBi()
  const [msg, setMsg] = useState<{ kind: 'error' | 'info' | 'success'; text: string } | null>(null)
  const approve = async (c: ApprovalCard) => {
    try {
      const out = await post<{ message: { en: string; ar: string } }>(`/api/companies/${companyId}/dashboard/approval-cards/${c.card_id}/approve`)
      setMsg({ kind: 'info', text: tx(out.message) })
      onChange()
    } catch (e) {
      const code = e instanceof ApiError ? e.code : ''
      setMsg({ kind: 'error', text: code === 'REAUTH_REQUIRED' ? t('reauth') : code === 'REQUEST_EXPIRED' ? t('request_expired') : code === 'APPROVAL_NOT_PERMITTED' ? t('only_owner_approve') : (e as Error).message })
    }
  }
  const cards = remote.approval_cards
  const waiting = cards.filter((c) => c.state === 'waiting')
  const earlier = cards.filter((c) => c.state !== 'waiting')
  const anyDemo = cards.some((c) => c.is_demo)
  return (
    <Panel
      title={<>{t('approvals')}{waiting.length > 0 && <span className="tab-badge dash-count">{waiting.length}</span>}</>}
      id="remote-approvals"
      className="dash-approvals"
      actions={anyDemo ? <Chip tone="neutral" icon="◇">{t('demo')}</Chip> : undefined}
    >
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      {cards.length === 0 ? <p className="muted">{t('approvals_empty')}</p> : (
        <>
          {waiting.length === 0 ? <p className="muted">{t('approvals_empty')}</p> : (
            <ul className="dash-rows">{waiting.map((c) => <ApprovalRow key={c.card_id} c={c} approve={approve} />)}</ul>
          )}
          {earlier.length > 0 && (
            <Disclosure summary={t('earlier_requests', { n: earlier.length })}>
              <ul className="dash-rows">{earlier.map((c) => <ApprovalRow key={c.card_id} c={c} approve={approve} />)}</ul>
            </Disclosure>
          )}
        </>
      )}
    </Panel>
  )
}

function ApprovalRow({ c, approve }: { c: ApprovalCard; approve: (c: ApprovalCard) => void }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const lang = i18n.language
  const ch = STATE_CHIP[c.state]
  const when = c.approve_by || c.decided_at || c.expires_at || ''
  const text = c.state === 'waiting' ? t('card_waiting') : c.state === 'approved' ? t('card_approved', { name: c.approver, time: formatDateTime(when, lang) }) : c.state === 'declined' ? t('card_declined', { name: c.approver, time: formatDateTime(when, lang) }) : t('card_expired', { time: formatDateTime(when, lang) })
  const local = when ? localLine(when, lang, t) : null
  return (
    <li className={`dash-approval ${c.state === 'waiting' ? 'dash-approval-waiting' : ''}`} aria-label={tx(c.what)}>
      <div className="dash-approval-head">
        <strong>{tx(c.what)}</strong>
        <Chip tone={ch.tone} icon={ch.icon}>{t(`state.${c.state}`)}</Chip>
      </div>
      <p className="dash-approval-text">{text}</p>
      <p className="dash-source">
        <span>{t('prepared_by')}: {tx(c.prepared_by)}</span>
        {c.state === 'waiting' && c.approve_by && <span>{t('approve_by', { time: formatDateTime(c.approve_by, lang) })}</span>}
        {local && <span>{local}</span>}
      </p>
      <div className="actions dash-approval-actions">
        {c.actions.includes('review_and_approve') && <Button onClick={() => approve(c)}>{t('review_and_approve')}</Button>}
        {c.actions.includes('decline') && <Button variant="secondary" disabled aria-disabled="true">{t('decline')}</Button>}
        {c.actions.includes('view_record') && <Button variant="secondary" disabled aria-disabled="true">{t('view_record')}</Button>}
        {c.actions.includes('ask_for_new_draft') && <Button variant="secondary" disabled aria-disabled="true">{t('ask_new_draft')}</Button>}
        {c.actions.includes('request_again') && <Button variant="secondary" disabled aria-disabled="true">{t('request_again')}</Button>}
      </div>
    </li>
  )
}
