import { Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../app/auth'
import { NAV } from '../features/registry'
import { Skeleton } from '../components/ui'
import { CompanySwitcher } from './CompanySwitcher'
import { IdleTimeout } from './IdleTimeout'
import { ResidencyStatement } from '../features/det/ResidencyStatement'
import { StoryBar } from '../features/demo/StoryBar'
import { Icon, NAV_ICONS } from '../components/Icon'

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

/** Brand mark: a licence card with a check, in the accent colour (bundled SVG, no external asset). */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <rect x="7" y="9" width="18" height="14" rx="2.5" fill="none" stroke="#fff" strokeWidth="1.8" />
      <path d="M11 16.2l2.6 2.6 5.4-5.6" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="25" cy="9" r="3.2" fill="#d4b483" stroke="var(--accent)" strokeWidth="1.4" />
    </svg>
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
        <button className="menu-btn" aria-label={t('nav.menu')} aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}><Icon name={menuOpen ? 'close' : 'menu'} /></button>
        <Link to="/" className="brand">
          <BrandMark />
          <span className="brand-text">
            <span className="brand-name">{t('app.short')}</span>
            <span className="brand-sub">{t('app.det')}</span>
          </span>
        </Link>
        <CompanySwitcher />
        <div className="topbar-end">
          <LanguageToggle />
          <div className="account">
            <button type="button" aria-haspopup="menu" aria-expanded={accountOpen} onClick={() => setAccountOpen((o) => !o)} className="account-btn">
              <span className="avatar" aria-hidden="true">{me.display_name.slice(0, 1)}</span>
              <span className="account-name"><bdi>{me.display_name}</bdi></span>
              <Icon name="chevron-down" size={16} className="account-chevron" />
            </button>
            {accountOpen && (
              <div className="menu" role="menu">
                <div className="menu-info"><bdi>{me.display_name}</bdi> · {me.assurance_level}</div>
                <button role="menuitem" onClick={async () => { await signOut(); nav('/signin') }}><Icon name="logout" size={18} /> {t('shell.sign_out')}</button>
              </div>
            )}
          </div>
        </div>
      </header>
      <StoryBar />
      {company && (
        <div className="acting-as" role="status">
          <Icon name="building" size={16} />
          <span>{t('shell.acting_as', { role: roleLabel, company: companyName })}</span>
        </div>
      )}
      <div className="layout">
        <nav className={`sidenav ${menuOpen ? 'open' : ''}`} aria-label={t('nav.menu')}>
          <ul>
            {items.map((n) => (
              <li key={n.path}>
                <NavLink to={n.path} end={n.path === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
                  <span aria-hidden="true" className="nav-icon">{NAV_ICONS[n.path] ? <Icon name={NAV_ICONS[n.path]} /> : n.icon}</span>
                  <span>{t(n.labelKey)}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <main id="main" ref={main} tabIndex={-1} className="main">
          <div className="main-inner">
            <Suspense fallback={<Skeleton rows={5} />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <nav className="bottombar" aria-label={t('nav.menu')}>
        {items.slice(0, 5).map((n) => (
          <NavLink key={n.path} to={n.path} end={n.path === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
            <span aria-hidden="true" className="nav-icon">{NAV_ICONS[n.path] ? <Icon name={NAV_ICONS[n.path]} /> : n.icon}</span>
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
