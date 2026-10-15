import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Empty, Message, Panel, Skeleton } from '../../components/ui'
import { ApiError, get } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import { LinkBadge, MaskedAccount, linkLine, useLang } from './parts'
import type { LinkRow, LinksOut } from './types'

export function useLinks(companyId: string | null) {
  const lang = useLang()
  const [data, setData] = useState<LinksOut | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [loading, setLoading] = useState(true)
  const load = useCallback(async () => {
    if (!companyId) return
    setLoading(true)
    try {
      setData(await get<LinksOut>(`/api/companies/${companyId}/links?lang=${lang}`))
      setError(null)
    } catch (e) {
      setError(e as Error)
    } finally {
      setLoading(false)
    }
  }, [companyId, lang])
  useEffect(() => {
    load()
  }, [load])
  return { data, error, loading, reload: load }
}

/** E4-S6 link status view: rows worst first, badge at the start edge, masked account, last refresh, next step. */
export default function LinkStatusList({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation('consent')
  const lang = useLang()
  const nav = useNavigate()
  const { companyId, can } = useAuth()
  const { data, error, loading, reload } = useLinks(companyId)
  const [filter, setFilter] = useState<'all' | 'attention'>('all')
  if (loading && !data) return <Skeleton rows={3} />
  if (error && !data) {
    if (error instanceof ApiError && error.status === 403) return <Message kind="info">{t('no_access')}</Message>
    return (
      <Message kind="error">
        {t('links_error')}{' '}
        <Button variant="link" onClick={reload}>{t('retry')}</Button>
      </Message>
    )
  }
  if (!data) return null
  const rows = data.rows.filter((r) => filter === 'all' || data.needs_attention.includes(r.link_id))
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
  const visibleRows = compact ? rows.slice(0, 5) : rows
  return (
    <div className="link-status">
      {!compact && (
        <div className="actions" role="group" aria-label={t('links_title')}>
          <Button variant={filter === 'all' ? 'primary' : 'secondary'} aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>{t('filter_all')}</Button>
          <Button variant={filter === 'attention' ? 'primary' : 'secondary'} aria-pressed={filter === 'attention'} onClick={() => setFilter('attention')}>{t('filter_attention')}</Button>
        </div>
      )}
      {visibleRows.length === 0 ? (
        <Empty title={t('links_empty')} body={t('links_empty_note')} action={<Button onClick={() => nav('/consent')}>{t('open_centre')}</Button>} />
      ) : (
        <ul className="link-rows" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {visibleRows.map((r) => (
            <LinkRowItem key={r.link_id} row={r} lang={lang} canAct={canAct} go={go} />
          ))}
        </ul>
      )}
      <div className="card" style={{ marginTop: 12 }}>
        <strong>{t('manual_line')}</strong>{' '}
        <Chip tone="draft" icon="✎">{t('manual_chip')}</Chip>{' '}
        {data.manual_uploads_line.badge === 'update_due' && <Chip tone="attention" icon="◷">{t('update_due')}</Chip>}
        <p className="muted" style={{ margin: '4px 0 0' }}>
          {data.manual_uploads_line.count > 0 && data.manual_uploads_line.latest_statement_end
            ? t('manual_line_body', { count: data.manual_uploads_line.count, date: formatDate(data.manual_uploads_line.latest_statement_end, lang) })
            : t('history_empty')}
        </p>
      </div>
    </div>
  )
}

function LinkRowItem({ row, lang, canAct, go }: { row: LinkRow; lang: string; canAct: (s: string) => boolean; go: (s: string) => void }) {
  const { t } = useTranslation('consent')
  return (
    <li className="card" style={{ marginBottom: 8, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <LinkBadge badge={row.badge} />
      <div style={{ flex: '1 1 260px' }}>
        <div>
          <strong>
            <bdi>{row.source_name}</bdi>
          </strong>{' '}
          <span className="muted">· {t(`source_type.${row.source_type}`)}</span> <MaskedAccount value={row.masked_account} />
          {row.is_demo && <span className="tag"> {t('demo')}</span>}
        </div>
        <div>{linkLine(t, row, lang)}</div>
        {row.still_connecting && <div role="status">{t('line.still_connecting')}</div>}
        <div className="muted" style={{ fontSize: '.9rem' }}>
          {t('last_refresh')}: {row.last_successful_refresh_at ? formatDateTime(row.last_successful_refresh_at, lang) : t('never')}
        </div>
        {row.manual_entries.map((m) => (
          <div key={m.tax_type} className="muted" style={{ fontSize: '.9rem' }}>
            {t('entry_age', { date: m.entered_at ? formatDate(m.entered_at.slice(0, 10), lang) : '' })} ({m.tax_type === 'vat' ? t('tax.vat') : t('tax.ct')})
          </div>
        ))}
      </div>
      {row.next_step && canAct(row.next_step) && (
        <Button variant="secondary" onClick={() => go(row.next_step!)}>{t(`btn.${row.next_step}`)}</Button>
      )}
    </li>
  )
}
