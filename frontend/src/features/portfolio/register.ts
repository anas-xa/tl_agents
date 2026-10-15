import { lazy } from 'react'
import { registerFeature } from '../registry'
import './i18n'

// SC12 Delegate portfolio. Nav 'My companies' order 15.
registerFeature(
  [{ path: '/portfolio', element: lazy(() => import('./Portfolio')), permission: 'portfolio.view', scope: 'company' }],
  [{ path: '/portfolio', labelKey: 'nav.portfolio', icon: '▤', permission: 'portfolio.view', scope: 'company', order: 15 }],
)
