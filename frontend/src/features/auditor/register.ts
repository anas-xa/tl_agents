import { lazy } from 'react'
import { registerFeature } from '../registry'
import './i18n'

registerFeature(
  [{ path: '/auditor', element: lazy(() => import('./AuditorWorkspace')), permission: 'engagements.view', scope: 'staff' }],
  [{ path: '/auditor', labelKey: 'nav.auditor', icon: '⚖', permission: 'engagements.view', scope: 'staff', order: 70 }],
)
