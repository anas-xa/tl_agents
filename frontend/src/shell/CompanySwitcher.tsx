import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../app/auth'
import { Icon } from '../components/Icon'

const SEARCH_THRESHOLD = 8 // illustrative, configurable (E1-S5)

/** Three modes: hidden (0 companies / staff), static (1), list (2+, searchable from 8). */
export function CompanySwitcher() {
  const { t, i18n } = useTranslation()
  const { me, company, setCompanyId } = useAuth()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])
  if (!me || me.companies.length === 0) return null
  const ar = i18n.language.startsWith('ar')
  const name = (c: { trade_name_en: string; trade_name_ar: string }) => (ar ? c.trade_name_ar : c.trade_name_en)
  if (me.companies.length === 1) return <span className="company-static"><bdi>{name(me.companies[0])}</bdi></span>
  const list = me.companies.filter((c) => !q || name(c).toLowerCase().includes(q.toLowerCase()) || c.trade_name_en.toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="switcher" ref={ref}>
      <button type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)} aria-label={`${t('shell.switch_company')}: ${company ? name(company) : ''} (${me.companies.length})`}>
        <bdi>{company ? name(company) : t('shell.switch_company')}</bdi> <Icon name="chevron-down" size={16} />
      </button>
      {open && (
        <div className="switcher-list">
          {me.companies.length >= SEARCH_THRESHOLD && (
            <input type="search" placeholder={t('shell.search_companies')} aria-label={t('shell.search_companies')} value={q} onChange={(e) => setQ(e.target.value)} />
          )}
          <ul role="listbox" aria-label={t('shell.switch_company')}>
            {list.map((c) => (
              <li key={c.company_id} role="option" aria-selected={c.company_id === company?.company_id}>
                <button type="button" onClick={() => { setCompanyId(c.company_id); setOpen(false) }}>
                  <bdi>{name(c)}</bdi>
                  {c.company_id === company?.company_id && <span className="current"> · {t('shell.current')}</span>}
                  <span className="muted"> · {c.roles.map((r) => t(`roles.${r}`)).join(', ')}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
