import { useTranslation } from 'react-i18next'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Placeholder } from '../../components/Placeholder'
import { Button } from '../../components/ui'
import { HOME_RESOLVERS } from '../registry'

/**
 * Home routes each role to its workspace. Feature modules register their landing page in
 * HOME_RESOLVERS (see home-registry.ts); without one, the role sees the matching placeholder.
 */
export default function Home() {
  const { t } = useTranslation()
  const { me, companyId, signOut } = useAuth()
  const [params] = useSearchParams()
  if (!me) return null
  for (const resolve of HOME_RESOLVERS) {
    const target = resolve(me, companyId)
    if (target) return <Navigate to={target} replace />
  }
  if (me.companies.length === 0 && me.staff_roles.length === 0) {
    return (
      <Placeholder
        variant="B"
        title={t('placeholder.no_companies_title')}
        body={t('placeholder.no_companies_body')}
        action={
          <div className="actions" style={{ justifyContent: 'center' }}>
            <Button variant="secondary">{t('placeholder.contact_det')}</Button>
            <Button variant="secondary" onClick={() => signOut()}>{t('shell.sign_out')}</Button>
          </div>
        }
      />
    )
  }
  if (me.staff_roles.some((r) => ['licensed_auditor', 'tax_specialist', 'legal_specialist'].includes(r)) && me.companies.length === 0) {
    return <Placeholder variant="B" title={t('placeholder.no_cases_title')} body={t('placeholder.no_cases_body')} />
  }
  if (params.get('no_company')) return <Placeholder variant="B" title={t('placeholder.no_companies_title')} body={t('placeholder.no_companies_body')} />
  return <Placeholder variant="A" />
}
