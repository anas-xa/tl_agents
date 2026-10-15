import { lazy } from 'react'
import { registerFeature } from '../registry'
import './i18n'

// SC15 owner/delegate activity list: owners see every actor on their company, delegates their own actions only.
registerFeature(
  [{ path: '/activity', element: lazy(() => import('./Activity')), permission: 'dashboard.view', scope: 'company' }],
  [{ path: '/activity', labelKey: 'activity:nav', icon: '≡', permission: 'dashboard.view', scope: 'company', order: 52 }],
)
