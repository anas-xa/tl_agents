import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Message, Panel, Skeleton } from '../../components/ui'
import { post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import { useBi, useFetch } from '../deadlines/lib'
import type { Inbox } from './types'

/** SC3 in-portal reminder inbox (E3-S4): unread / acknowledged, held-translation notices, next planned reminders. */
export default function InboxPanel() {
  const { t, i18n } = useTranslation('reminders')
  const { tx, lang } = useBi()
  const { companyId } = useAuth()
  const { data, error, loading, reload } = useFetch<Inbox>(companyId ? `/api/companies/${companyId}/reminders` : null)
  const [failures, setFailures] = useState(0)
  if (loading && !data) return <Panel title={t('inbox_title')}><p aria-busy="true">{t('loading')}</p><Skeleton rows={3} /></Panel>
  if (error && !data) {
    return (
      <Panel title={t('inbox_title')}>
        <Message kind="error">{t('error')}</Message>
        <Button variant="secondary" onClick={() => { setFailures(failures + 1); reload() }}>{t('try_again')}</Button>
        {failures >= 2 && <Button variant="link">{t('contact_support')}</Button>}
      </Panel>
    )
  }
  if (!data) return null
  const ack = async (id: string) => {
    await post(`/api/companies/${companyId}/reminders/${id}/acknowledge`)
    reload()
  }
  return (
    <Panel title={<>{t('inbox_title')} {data.unread > 0 && <Chip tone="info" icon="●">{t('unread')} {data.unread}</Chip>}</>} id="reminders-inbox">
      {data.held_notices.map((n) => <Message key={n.reminder_id} kind="warning">{tx(n.text)}</Message>)}
      {data.items.length === 0 ? (
        <p>{t('empty')} <Link to="/settings?tab=reminders">{t('open_settings')}</Link></p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {data.items.slice(0, 8).map((r) => (
            <li key={r.reminder_id} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
              <div>{(lang === 'ar' ? r.body.ar : r.body.en) || r.body.en || r.body.ar}</div>
              <div className="helper" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                {r.sent_at && <span>{t('sent', { time: formatDateTime(r.sent_at, i18n.language) })}</span>}
                {r.flags.includes('catch-up') && <Chip tone="info" icon="↻">{t('catch_up')}</Chip>}
                {r.flags.includes('date_under_review') && <Chip tone="attention" icon="!">{t('date_under_review')}</Chip>}
                {r.flags.includes('no_owner_level_user') && <Chip tone="attention" icon="!">{t('no_owner_user')}</Chip>}
                {r.is_demo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}
                {r.inbox_state === 'unread' && <Button variant="link" onClick={() => ack(r.reminder_id)}>{t('acknowledge')}</Button>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {data.upcoming.length > 0 && (
        <details>
          <summary>{t('upcoming')}</summary>
          <ul>{data.upcoming.map((r) => <li key={r.reminder_id}>{formatDate(r.planned_date, i18n.language)} · {t(`channel.${r.channel}`)}</li>)}</ul>
        </details>
      )}
    </Panel>
  )
}
