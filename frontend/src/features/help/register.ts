import { lazy } from 'react'
import { registerFeature } from '../registry'
import './i18n'

registerFeature(
  [{ path: '/help', element: lazy(() => import('./Help')), permission: 'escalation.view', scope: 'company' }],
  [{ path: '/help', labelKey: 'nav.help', icon: '?', permission: 'escalation.view', scope: 'company', order: 60 }],
)
