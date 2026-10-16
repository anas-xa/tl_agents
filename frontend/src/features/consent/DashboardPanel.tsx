import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Disclosure, Empty, Message, Panel, Skeleton } from '../../components/ui'
import { ApiError } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import { useLinks } from './LinkStatusList'
import { LinkBadge, MaskedAccount, linkLine, useLang } from './parts'
import type { LinkRow } from './types'

/** SC3 'Data links' panel (E4-S6): compact link status, worst first. Links that need no action yet
 * ("Not available yet") are folded behind one disclosure; their next step stays one click away. */
export default function DashboardPanel() {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const nav = useNavigate()
  const { companyId, can } = useAuth()
  const { data, error, loading, reload } = useLinks(companyId)
  const title = t('links_title')
  const actions = can('consent.view', companyId) ? <Link to="/consent">{t('open_centre')}</Link> : undefined
  if (loading && !data) return <Panel title={title} id="dash-links"><Skeleton rows={3} /></Panel>
  if (error && !data) {
    return (
      <Panel title={title} id="dash-links">
        {error instanceof ApiError && error.status === 403 ? <Message kind="info">{t('no_access')}</Message> : (
          <Message kind="error">{t('links_error')} <Button variant="link" onClick={reload}>{t('retry')}</Button></Message>
        )}
      </Panel>
    )
  }
  if (!data) return null
  const canAct = (step: string) => {
    if (data.remote_owner_read_only) return false
    if (step === 'upload_files') return can('uploads.manage', companyId)
    if (step === 'renew_consent' || step === 'open_consent_centre') return can('consent.view', companyId)
    if (step === 'enter_manually') return can('taxprofile.edit', companyId)
    return can('links.manage', companyId)
  }
  const go = (step: string) => {
    if (step === 'upload_files') nav('/settings?tab=data-links')
    else if (step === 'enter_manually') nav('/consent#tax-link')
    else nav('/consent')
  }
  const main = data.rows.filter((r) => r.badge !== 'not_available_yet')
  const later = data.rows.filter((r) => r.badge === 'not_available_yet')
  const anyDemo = data.rows.some((r) => r.is_demo)
  const m = data.manual_uploads_line
  return (
    <Panel title={title} id="dash-links" actions={<>{anyDemo && <Chip tone="neutral" icon="◇">{t('demo')}</Chip>}{actions}</>}>
      {data.rows.length === 0 ? (
        <Empty title={t('links_empty')} body={t('links_empty_note')} action={<Button onClick={() => nav('/consent')}>{t('open_centre')}</Button>} />
      ) : (
        <ul className="dash-status-list">
          {main.map((r) => <Row key={r.link_id} row={r} lang={lang} canAct={canAct} go={go} />)}
        </ul>
      )}
      <div className="dash-links-manual">
        <span className="dash-labels">
          <strong>{t('manual_line')}</strong>
          <Chip tone="draft" icon="✎">{t('manual_chip')}</Chip>
          {m.badge === 'update_due' && <Chip tone="attention" icon="◷">{t('update_due')}</Chip>}
        </span>
        <p className="dash-source">
          {m.count > 0 && m.latest_statement_end ? t('manual_line_body', { count: m.count, date: formatDate(m.latest_statement_end, lang) }) : t('history_empty')}
        </p>
      </div>
      {later.length > 0 && (
        <Disclosure summary={t('dashboard:links_not_available', { n: later.length })}>
          <ul className="dash-status-list">
            {later.map((r) => <Row key={r.link_id} row={r} lang={lang} canAct={canAct} go={go} quiet />)}
          </ul>
        </Disclosure>
      )}
    </Panel>
  )
}

function Row({ row, lang, canAct, go, quiet = false }: { row: LinkRow; lang: string; canAct: (s: string) => boolean; go: (s: string) => void; quiet?: boolean }) {
  const { t } = useTranslation('consent')
  return (
    <li>
      <span className="dash-status-name">
        <strong><bdi>{row.source_name}</bdi></strong>{' '}
        <span className="muted">· {t(`source_type.${row.source_type}`)}</span> <MaskedAccount value={row.masked_account} />
      </span>
      <span className="dash-status-end">
        {!quiet && <LinkBadge badge={row.badge} />}
        {row.next_step && canAct(row.next_step) && (
          <Button variant="secondary" className="dash-link-btn" onClick={() => go(row.next_step!)}>{t(`btn.${row.next_step}`)}</Button>
        )}
      </span>
      <span className="dash-status-sub">
        {linkLine(t, row, lang)}
        {row.still_connecting && <span role="status"> {t('line.still_connecting')}</span>}
        {!quiet && row.badge !== 'active' && <> · {t('last_refresh')}: {row.last_successful_refresh_at ? formatDateTime(row.last_successful_refresh_at, lang) : t('never')}</>}
        {row.manual_entries.map((me) => (
          <span key={me.tax_type} className="dash-block">
            {t('entry_age', { date: me.entered_at ? formatDate(me.entered_at.slice(0, 10), lang) : '' })} ({me.tax_type === 'vat' ? t('tax.vat') : t('tax.ct')})
          </span>
        ))}
      </span>
    </li>
  )
}
