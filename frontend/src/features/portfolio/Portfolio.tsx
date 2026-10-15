import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Empty, Message, Panel, Skeleton } from '../../components/ui'
import { daysLeftLabel, formatDate } from '../../lib/format'
import { tierTone, useBi, useFetch, type Bi, type Obligation } from '../deadlines/lib'
import { ReadinessChip } from '../deadlines/parts'

interface Row { company_id: string; trade_name_en: string; trade_name_ar: string; role: string; functions: string[]; nearest_days_left: number | null; obligations: Obligation[]; withheld_count: number; can_send_for_approval: boolean; can_approve: boolean; access_limits: Bi[] }

/** SC12 Delegate portfolio: companies sorted by nearest deadline, missing items per obligation, access limits. */
export default function Portfolio() {
  const { t, i18n } = useTranslation('portfolio')
  const { tx, lang } = useBi()
  const { setCompanyId } = useAuth()
  const nav = useNavigate()
  const { data, error, loading, reload } = useFetch<{ companies: Row[] }>('/api/me/portfolio')
  if (loading && !data) return <Panel><p aria-busy="true">{t('loading')}</p><Skeleton rows={4} /></Panel>
  if (error && !data) return <Message kind="error">{t('error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message>
  if (!data || data.companies.length === 0) return <Empty title={t('empty')} />
  return (
    <div>
      <h1>{t('title')}</h1>
      <p className="helper">{t('intro')}</p>
      {data.companies.map((c) => (
        <Panel key={c.company_id} title={<bdi>{lang === 'ar' ? c.trade_name_ar : c.trade_name_en}</bdi>} actions={<Button variant="secondary" onClick={() => { setCompanyId(c.company_id); nav('/dashboard') }}>{t('open_dashboard')}</Button>}>
          <p>
            {t('nearest')}: {c.nearest_days_left === null ? t('none_dated') : <Chip tone={tierTone(c.nearest_days_left < 0 ? 'critical' : c.nearest_days_left <= 7 ? 'urgent' : c.nearest_days_left <= 30 ? 'attention' : 'neutral').tone} icon="◷">{daysLeftLabel(c.nearest_days_left, i18n.language)}</Chip>}
          </p>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {c.obligations.map((o) => (
              <li key={o.obligation_id} className="card" style={{ marginBottom: 8 }}>
                <strong>{tx(o.name)}</strong> · {o.due_date ? formatDate(o.due_date, i18n.language) : t('undated')} {o.days_left !== null && <Chip tone={tierTone(o.days_left_tier).tone} icon={tierTone(o.days_left_tier).icon}>{daysLeftLabel(o.days_left, i18n.language)}</Chip>} <ReadinessChip o={o} />
                {o.missing_items.length > 0 ? (
                  <ul className="helper" style={{ margin: '4px 0', paddingInlineStart: 18 }}>
                    {o.missing_items.map((m) => <li key={m.code}><Chip tone="attention" icon="!">{t('missing')}</Chip> {lang === 'ar' ? m.label_ar : m.label_en}</li>)}
                  </ul>
                ) : <p className="helper" style={{ margin: '4px 0' }}>{t('nothing_missing')}</p>}
                {o.draft_pack_id && (
                  <div className="actions">
                    {c.can_send_for_approval ? <Link to={`/returns/${o.draft_pack_id}`}>{t('send_pack')}</Link> : <Link to={`/returns/${o.draft_pack_id}`}>{t('open_draft')}</Link>}
                    {!c.can_approve && <span className="helper">{t('only_owner_approve')}</span>}
                  </div>
                )}
              </li>
            ))}
          </ul>
          {c.withheld_count > 0 && <p className="helper">{t('withheld')}</p>}
          <details>
            <summary>{t('access_limits')}</summary>
            <ul>{c.access_limits.map((a, i) => <li key={i}>{tx(a)}</li>)}</ul>
          </details>
        </Panel>
      ))}
    </div>
  )
}
