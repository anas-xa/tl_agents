import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Message, Panel } from '../../components/ui'
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

/** E3-S5 remote-owner strip: freshness banner and the approval cards in their four states (Demo data fixtures). */
export default function RemoteStrip({ remote, companyId, onChange }: { remote: NonNullable<Dashboard['remote']>; companyId: string; onChange: () => void }) {
  const { t, i18n } = useTranslation('dashboard')
  const { tx } = useBi()
  const [msg, setMsg] = useState<{ kind: 'error' | 'info' | 'success'; text: string } | null>(null)
  const lang = i18n.language
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
  const fb = remote.freshness_banner
  return (
    <div>
      {fb.last_update && <Message kind={fb.sources_not_current ? 'warning' : 'info'}>{t('freshness_banner', { time: formatDateTime(fb.last_update, lang), n: fb.sources_not_current })}</Message>}
      <Panel title={t('approvals')}>
        {msg && <Message kind={msg.kind}>{msg.text}</Message>}
        {remote.approval_cards.length === 0 ? <p>{t('approvals_empty')}</p> : (
          <div className="grid">
            {remote.approval_cards.map((c) => {
              const ch = STATE_CHIP[c.state]
              const when = c.approve_by || c.decided_at || c.expires_at || ''
              const text = c.state === 'waiting' ? t('card_waiting') : c.state === 'approved' ? t('card_approved', { name: c.approver, time: formatDateTime(when, lang) }) : c.state === 'declined' ? t('card_declined', { name: c.approver, time: formatDateTime(when, lang) }) : t('card_expired', { time: formatDateTime(when, lang) })
              const local = when ? localLine(when, lang, t) : null
              return (
                <section key={c.card_id} className="card" aria-label={tx(c.what)}>
                  <p><Chip tone={ch.tone} icon={ch.icon}>{text.split('.')[0]}</Chip> {c.is_demo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}</p>
                  <p><strong>{tx(c.what)}</strong></p>
                  <p className="helper">{t('prepared_by')}: {tx(c.prepared_by)}</p>
                  <p>{text}</p>
                  {c.state === 'waiting' && c.approve_by && <p className="helper">{t('approve_by', { time: formatDateTime(c.approve_by, lang) })}{local ? <><br />{local}</> : null}</p>}
                  {c.state !== 'waiting' && local && <p className="helper">{local}</p>}
                  <div className="actions">
                    {c.actions.includes('review_and_approve') && <Button onClick={() => approve(c)}>{t('review_and_approve')}</Button>}
                    {c.actions.includes('decline') && <Button variant="secondary" disabled aria-disabled="true">{t('decline')}</Button>}
                    {c.actions.includes('view_record') && <Button variant="secondary" disabled aria-disabled="true">{t('view_record')}</Button>}
                    {c.actions.includes('ask_for_new_draft') && <Button variant="secondary" disabled aria-disabled="true">{t('ask_new_draft')}</Button>}
                    {c.actions.includes('request_again') && <Button variant="secondary" disabled aria-disabled="true">{t('request_again')}</Button>}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}
