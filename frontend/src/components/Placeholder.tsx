import { useEffect, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../app/auth'
import { Button } from './ui'

/**
 * Placeholder component (E1-S5): exactly three variants.
 * A: 'Not available yet' (clock icon, phase tag, no button)
 * B: 'Nothing here yet' (inbox icon, optional contact button)
 * C: 'No access' (lock icon, Back to Home + optional Contact the company owner)
 */
export function Placeholder({ variant, title, body, action }: { variant: 'A' | 'B' | 'C'; title?: ReactNode; body?: ReactNode; action?: ReactNode }) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const { me } = useAuth()
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  const icon = variant === 'A' ? '◷' : variant === 'B' ? '▭' : '🔒'
  const isOwnerOrDet = !!me && (me.staff_roles.length > 0 || me.companies.some((c) => c.roles.includes('owner') || c.roles.includes('remote_owner')))
  return (
    <div className={`placeholder placeholder-${variant}`}>
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <h2 ref={heading} tabIndex={-1}>
        {title ?? t(`placeholder.${variant}_title`)}
        {variant === 'A' && <span className="tag"> {t('placeholder.A_tag')}</span>}
      </h2>
      <p>{body ?? (variant === 'A' ? t('placeholder.A_body') : variant === 'C' ? t('placeholder.C_body') : null)}</p>
      {variant === 'C' && (
        <div className="actions">
          <Button onClick={() => nav('/')}>{t('placeholder.back_home')}</Button>
          {!isOwnerOrDet && <Button variant="secondary">{t('placeholder.contact_owner')}</Button>}
        </div>
      )}
      {variant === 'B' && action}
    </div>
  )
}
