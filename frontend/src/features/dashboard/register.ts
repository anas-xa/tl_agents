import { lazy } from 'react'
import { registerFeature, registerHome } from '../registry'
import './i18n'

// SC3 Company dashboard (E3-S1, E3-S3 card group, E3-S5 remote-owner variant).
registerFeature([{ path: '/dashboard', element: lazy(() => import('./Dashboard')), permission: 'dashboard.view', scope: 'company' }])

// Company users land on the dashboard; a delegate with two or more companies lands on the portfolio (SC12).
registerHome((me) => {
  if (!me.companies.length) return null
  const roles = me.companies.flatMap((c) => c.roles)
  if (!roles.some((r) => ['owner', 'remote_owner', 'delegate'].includes(r))) return null
  const delegateCompanies = me.companies.filter((c) => c.roles.includes('delegate')).length
  const ownerLevel = roles.some((r) => r === 'owner' || r === 'remote_owner')
  if (!ownerLevel && delegateCompanies >= 2) return '/portfolio'
  return '/dashboard'
})
