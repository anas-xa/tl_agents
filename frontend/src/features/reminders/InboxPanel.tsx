import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Disclosure, Message, Panel, Skeleton } from '../../components/ui'
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
  if (loading && !data) return <Panel title={t('inbox_title')} id="reminders-inbox"><p aria-busy="true" className="visually-hidden">{t('loading')}</p><Skeleton rows={2} /></Panel>
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
  const anyDemo = data.items.some((r) => r.is_demo)
  return (
    <Panel
      title={<>{t('inbox_title')}{data.unread > 0 && <Chip tone="info" icon="●">{t('unread')} {data.unread}</Chip>}</>}
      id="reminders-inbox"
      actions={anyDemo ? <Chip tone="neutral" icon="◇">{t('demo')}</Chip> : undefined}
    >
      {data.held_notices.map((n) => <Message key={n.reminder_id} kind="warning">{tx(n.text)}</Message>)}
      {data.items.length === 0 ? (
        <p className="muted">{t('empty')} <Link to="/settings?tab=reminders">{t('open_settings')}</Link></p>
      ) : (
        <ul className="dash-rows">
          {data.items.slice(0, 8).map((r) => (
            <li key={r.reminder_id} className="dash-row">
              <span className="dash-row-main">{(lang === 'ar' ? r.body.ar : r.body.en) || r.body.en || r.body.ar}</span>
              <span className="dash-status-end">
                {r.sent_at && <span className="muted">{t('sent', { time: formatDateTime(r.sent_at, i18n.language) })}</span>}
                {r.flags.includes('catch-up') && <Chip tone="info" icon="↻">{t('catch_up')}</Chip>}
                {r.flags.includes('date_under_review') && <Chip tone="attention" icon="!">{t('date_under_review')}</Chip>}
                {r.flags.includes('no_owner_level_user') && <Chip tone="attention" icon="!">{t('no_owner_user')}</Chip>}
                {r.inbox_state === 'unread' && <Button variant="link" onClick={() => ack(r.reminder_id)}>{t('acknowledge')}</Button>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {data.upcoming.length > 0 && (
        <Disclosure summary={t('upcoming')}>
          <ul className="dash-rows">{data.upcoming.map((r) => <li key={r.reminder_id} className="dash-row"><span className="nowrap">{formatDate(r.planned_date, i18n.language)}</span><span className="muted">{t(`channel.${r.channel}`)}</span></li>)}</ul>
        </Disclosure>
      )}
    </Panel>
  )
}
