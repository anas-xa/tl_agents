import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Disclosure, Empty, Message, PageHeader, Skeleton } from '../../components/ui'
import { daysLeftLabel, formatDate } from '../../lib/format'
import { tierTone, useBi, useFetch, type Bi, type Obligation } from '../deadlines/lib'
import { ReadinessChip } from '../deadlines/parts'
import './portfolio.css'

interface Row { company_id: string; trade_name_en: string; trade_name_ar: string; role: string; functions: string[]; nearest_days_left: number | null; obligations: Obligation[]; withheld_count: number; can_send_for_approval: boolean; can_approve: boolean; access_limits: Bi[] }

/** SC12 Delegate portfolio: companies sorted by nearest deadline, missing items per obligation, access limits. */
export default function Portfolio() {
  const { t, i18n } = useTranslation('portfolio')
  const { tx, lang } = useBi()
  const { setCompanyId } = useAuth()
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const { data, error, loading, reload } = useFetch<{ companies: Row[] }>('/api/me/portfolio')
  const header = <PageHeader title={t('title')} subtitle={t('intro')} meta={data ? <span className="pf-count"><Icon name="building" size={16} />{t('count', { count: data.companies.length })}</span> : undefined} />
  if (loading && !data) return <div>{header}<div className="card"><p aria-busy="true">{t('loading')}</p><Skeleton rows={4} /></div></div>
  if (error && !data) return <div>{header}<Message kind="error">{t('error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message></div>
  if (!data || data.companies.length === 0) return <div>{header}<Empty icon="briefcase" title={t('empty')} /></div>
  const needle = q.trim().toLowerCase()
  const shown = needle ? data.companies.filter((c) => `${c.trade_name_en} ${c.trade_name_ar}`.toLowerCase().includes(needle)) : data.companies
  const tierOf = (d: number | null) => (d === null ? 'unknown' : d < 0 ? 'critical' : d <= 7 ? 'urgent' : d <= 30 ? 'attention' : 'neutral')
  return (
    <div className="pf-page">
      {header}
      {data.companies.length > 3 && (
        <div className="pf-search">
          <label htmlFor="pf-q" className="visually-hidden">{t('search')}</label>
          <Icon name="search" size={18} />
          <input id="pf-q" type="search" value={q} placeholder={t('search')} onChange={(e) => setQ(e.target.value)} />
        </div>
      )}
      {shown.length === 0 && <Empty icon="search" title={t('no_match')} />}
      <div className="pf-grid">
        {shown.map((c) => {
          const name = lang === 'ar' ? c.trade_name_ar : c.trade_name_en
          const tier = tierTone(tierOf(c.nearest_days_left))
          return (
            <section key={c.company_id} className={`card pf-card pf-tier-${tierOf(c.nearest_days_left)}`} aria-labelledby={`pf-${c.company_id}`}>
              <header className="pf-head">
                <span className="pf-mark" aria-hidden="true">{name.trim().charAt(0)}</span>
                <div className="pf-head-text">
                  <h2 id={`pf-${c.company_id}`}><bdi>{name}</bdi></h2>
                  <p className="pf-next">
                    <span className="pf-next-label">{t('nearest')}</span>
                    {c.nearest_days_left === null ? <span className="muted">{t('none_dated')}</span> : <Chip tone={tier.tone} icon={tier.icon}>{daysLeftLabel(c.nearest_days_left, i18n.language)}</Chip>}
                  </p>
                </div>
              </header>
              {c.obligations.length > 0 && (
                <ul className="pf-obls">
                  {c.obligations.map((o) => (
                    <li key={o.obligation_id}>
                      <div className="pf-obl-top">
                        <strong>{tx(o.name)}</strong>
                        <span className="pf-obl-date nowrap">{o.due_date ? formatDate(o.due_date, i18n.language) : t('undated')}</span>
                      </div>
                      <div className="pf-obl-chips">
                        {o.days_left !== null && <Chip tone={tierTone(o.days_left_tier).tone} icon={tierTone(o.days_left_tier).icon}>{daysLeftLabel(o.days_left, i18n.language)}</Chip>}
                        <ReadinessChip o={o} />
                      </div>
                      {o.missing_items.length > 0 ? (
                        <ul className="pf-missing">
                          {o.missing_items.map((m) => <li key={m.code}><Chip tone="attention" icon="!">{t('missing')}</Chip> <span>{lang === 'ar' ? m.label_ar : m.label_en}</span></li>)}
                        </ul>
                      ) : <p className="pf-ok"><Icon name="check" size={14} />{t('nothing_missing')}</p>}
                      {o.draft_pack_id && (
                        <div className="pf-obl-action">
                          {c.can_send_for_approval ? <Link to={`/returns/${o.draft_pack_id}`}>{t('send_pack')}</Link> : <Link to={`/returns/${o.draft_pack_id}`}>{t('open_draft')}</Link>}
                          {!c.can_approve && <span className="helper">{t('only_owner_approve')}</span>}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <footer className="pf-foot">
                {c.withheld_count > 0 && <p className="helper">{t('withheld')}</p>}
                <Disclosure summary={t('access_limits')} className="pf-limits">
                  <ul>{c.access_limits.map((a, i) => <li key={i}>{tx(a)}</li>)}</ul>
                </Disclosure>
                <Button variant="secondary" className="pf-open" onClick={() => { setCompanyId(c.company_id); nav('/dashboard') }}>
                  {t('open_dashboard')}<Icon name="chevron-end" size={16} className="flip-rtl" />
                </Button>
              </footer>
            </section>
          )
        })}
      </div>
    </div>
  )
}
