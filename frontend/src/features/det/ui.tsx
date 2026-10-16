import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon, type IconName } from '../../components/Icon'
import { Chip } from '../../components/ui'
import { daysLeftLabel } from '../../lib/format'
import { daysUntil } from './headerMeta'
import './det.css'

/**
 * Small presentational pieces shared by the DET dashboard tabs and the specialist workspaces
 * (requests and complaints, case queue, auditor workspace). Styles live in det.css (prefix det-).
 */

/** Reply-by / deadline clock: icon + text, tinted by how close the date is. Nothing when the item is done. */
export function DueChip({ date, done }: { date: string | null | undefined; done?: boolean }) {
  const { i18n } = useTranslation()
  const days = daysUntil(date)
  if (done || days === null) return null
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const tone = days < 0 ? 'critical' : days <= 2 ? 'urgent' : days <= 7 ? 'attention' : 'neutral'
  return <Chip tone={tone} icon={days < 0 ? '!' : '◷'}>{daysLeftLabel(days, lang)}</Chip>
}

/** "What to do next" line under a workspace header. */
export function NextStep({ children, icon = 'play', action, tone = 'accent' }: { children: ReactNode; icon?: IconName; action?: ReactNode; tone?: 'accent' | 'calm' }) {
  const { t } = useTranslation('det')
  return (
    <div className={`det-next det-next-${tone}`} role="note">
      <span className="det-next-icon" aria-hidden="true"><Icon name={icon} size={18} className="flip-rtl" /></span>
      <div className="det-next-text">
        <span className="det-next-label">{t('ws_next')}</span>
        <span>{children}</span>
      </div>
      {action && <div className="det-next-action">{action}</div>}
    </div>
  )
}

/** Direction arrow for trend lines (the shared icon set has no arrows). */
export function TrendArrow({ dir }: { dir: 'up' | 'down' | 'flat' }) {
  const d = dir === 'up' ? 'M12 19V5m-6 6 6-6 6 6' : dir === 'down' ? 'M12 5v14m6-6-6 6-6-6' : 'M5 12h14m-6-6 6 6-6 6'
  return (
    <svg className={dir === 'flat' ? 'flip-rtl' : undefined} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={d} />
    </svg>
  )
}

/** Section heading row inside a tab: h2 + optional hint + actions on the end side. */
export function SectionHead({ id, title, hint, actions, level = 2, first }: { id?: string; title: ReactNode; hint?: ReactNode; actions?: ReactNode; level?: 2 | 3; first?: boolean }) {
  const H = level === 2 ? 'h2' : 'h3'
  return (
    <div className={`det-section-head ${first ? 'is-first' : ''}`}>
      <div className="det-section-head-text">
        <H id={id}>{title}</H>
        {hint && <p className="det-section-hint">{hint}</p>}
      </div>
      {actions && <div className="det-section-actions">{actions}</div>}
    </div>
  )
}

/** Quiet provenance line: items separated by middle dots, wraps on small screens. */
export function MetaLine({ items, className }: { items: ReactNode[]; className?: string }) {
  const shown = items.filter((x) => x !== null && x !== undefined && x !== false && x !== '')
  return (
    <span className={`det-meta ${className ?? ''}`}>
      {shown.map((x, i) => (
        <span key={i} className="det-meta-item">{x}</span>
      ))}
    </span>
  )
}
