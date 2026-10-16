import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Chip, Empty, Message, Skeleton } from '../../components/ui'
import { get } from '../../lib/api'
import { formatDateTime, iso } from '../../lib/format'
import { errorKey, type PackSummary } from './types'

/** Draft returns for the company (E5-S3). Held drafts are listed for the owner only. */
export default function DraftsList({ companyId }: { companyId: string }) {
  const { t, i18n } = useTranslation('tax')
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const [packs, setPacks] = useState<PackSummary[] | null>(null)
  const [held, setHeld] = useState(0)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    get<{ packs: PackSummary[]; held_count: number }>(`/api/companies/${companyId}/drafts`)
      .then((r) => { setPacks(r.packs); setHeld(r.held_count) })
      .catch((e) => setError(t(errorKey(e).key)))
  }, [companyId, t])
  if (error) return <Message kind="info">{error}</Message>
  if (!packs) return <Skeleton rows={3} />
  if (packs.length === 0) return <Empty icon="file" title={t('no_draft_title')} body={t('no_draft')} action={<Link className="btn btn-primary" to="/tax?tab=vat">{t('go_calculate')}</Link>} />
  return (
    <>
      {held > 0 && <Message kind="warning">{t('held_intro', { name: packs.find((p) => p.on_hold)?.held_delegate ?? '' })}</Message>}
      <div className="card tax-table">
        <div className="table-wrap">
          <table className="table-compact tax-drafts">
            <thead>
              <tr>
                <th scope="col">{t('period')}</th>
                <th scope="col">{t('col_status')}</th>
                <th scope="col">{t('versions')}</th>
                <th scope="col">{t('col_date')}</th>
              </tr>
            </thead>
            <tbody>
              {packs.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link className="tax-row-link" to={`/returns/${p.id}`}>{t('draft_for', { type: t(p.tax_type === 'vat' ? 'tax_type_vat' : 'tax_type_ct'), period: iso(p.period_id) })}</Link>
                    {p.is_demo && <> <Chip tone="neutral">{t('demo')}</Chip></>}
                  </td>
                  <td>
                    <Chip tone={p.superseded ? 'neutral' : 'draft'}>{t(`st_${p.review_status}`)}</Chip>
                    {p.on_hold && <> <Chip tone="critical" icon="⏸">{t('on_hold')}</Chip></>}
                  </td>
                  <td className="nowrap"><bdi dir="ltr">{t('version_n', { n: p.version })}</bdi></td>
                  <td className="date-cell">{formatDateTime(p.created_at, lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
