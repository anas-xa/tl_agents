import { Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../app/auth'
import { NAV } from '../features/registry'
import { Skeleton } from '../components/ui'
import { CompanySwitcher } from './CompanySwitcher'
import { IdleTimeout } from './IdleTimeout'
import { ResidencyStatement } from '../features/det/ResidencyStatement'

export function LanguageToggle() {
  const { i18n } = useTranslation()
  const { setLanguage } = useAuth()
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  return (
    <div className="lang-toggle" role="group" aria-label={i18n.t('lang.label')}>
      <button type="button" lang="ar" aria-pressed={lang === 'ar'} onClick={() => setLanguage('ar')} className={lang === 'ar' ? 'active' : ''}>
        العربية
      </button>
      <button type="button" lang="en" aria-pressed={lang === 'en'} onClick={() => setLanguage('en')} className={lang === 'en' ? 'active' : ''}>
        English
      </button>
    </div>
  )
}

export function Shell() {
  const { t } = useTranslation()
  const { me, company, companyId, can, signOut, loading } = useAuth()
  const nav = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const main = useRef<HTMLElement>(null)

  useEffect(() => {
    setMenuOpen(false)
    main.current?.focus()
  }, [location.pathname])

  if (loading && !me) return <div className="page"><Skeleton rows={4} /></div>
  if (!me) return null

  const items = NAV.filter((n) => {
    if (n.scope === 'staff') return !!n.permission && me.staff_permissions.includes(n.permission)
    if (n.scope === 'company') return !!companyId && (!n.permission || can(n.permission, companyId))
    return true
  })
    .filter((n, i, all) => all.findIndex((m) => m.path === n.path) === i) // one entry per path even if several permissions grant it
    .sort((a, b) => a.order - b.order)

  const roleLabel = company ? company.roles.map((r) => t(`roles.${r}`)).join(', ') : me.staff_roles.map((r) => t(`roles.${r}`)).join(', ')
  const companyName = company ? (t('lang.ar') === 'العربية' && document.documentElement.lang === 'ar' ? company.trade_name_ar : company.trade_name_en) : ''

  return (
    <div className="shell">
      <a className="skip-link" href="#main">{t('nav.skip')}</a>
      <header className="topbar">
        <button className="menu-btn" aria-label={t('nav.menu')} aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>☰</button>
        <Link to="/" className="brand">{t('app.short')}</Link>
        <CompanySwitcher />
        <div className="topbar-end">
          <LanguageToggle />
          <div className="account">
            <button type="button" aria-haspopup="menu" aria-expanded={accountOpen} onClick={() => setAccountOpen((o) => !o)} className="account-btn">
              <span className="avatar" aria-hidden="true">{me.display_name.slice(0, 1)}</span>
              <span className="account-name"><bdi>{me.display_name}</bdi></span>
            </button>
            {accountOpen && (
              <div className="menu" role="menu">
                <div className="menu-info"><bdi>{me.display_name}</bdi> · {me.assurance_level}</div>
                <button role="menuitem" onClick={async () => { await signOut(); nav('/signin') }}>{t('shell.sign_out')}</button>
              </div>
            )}
          </div>
        </div>
      </header>
      {company && (
        <div className="acting-as" role="status">
          {t('shell.acting_as', { role: roleLabel, company: companyName })}
        </div>
      )}
      <div className="layout">
        <nav className={`sidenav ${menuOpen ? 'open' : ''}`} aria-label={t('nav.menu')}>
          <ul>
            {items.map((n) => (
              <li key={n.path}>
                <NavLink to={n.path} end={n.path === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
                  <span aria-hidden="true" className="nav-icon">{n.icon}</span>
                  <span>{t(n.labelKey)}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <main id="main" ref={main} tabIndex={-1} className="main">
          <Suspense fallback={<Skeleton rows={5} />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <nav className="bottombar" aria-label={t('nav.menu')}>
        {items.slice(0, 5).map((n) => (
          <NavLink key={n.path} to={n.path} end={n.path === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
            <span aria-hidden="true">{n.icon}</span>
            <span>{t(n.labelKey)}</span>
          </NavLink>
        ))}
      </nav>
      <footer className="footer">
        <span className="residency"><ResidencyStatement compact /></span>
        <span className="footer-links">
          <Link to="/help">{t('shell.help')}</Link> · <Link to="/privacy">{t('shell.privacy')}</Link> · <Link to="/accessibility">{t('shell.accessibility')}</Link>
        </span>
      </footer>
      <IdleTimeout />
    </div>
  )
}
