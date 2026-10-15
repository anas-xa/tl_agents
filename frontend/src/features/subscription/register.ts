import { lazy } from 'react'
import { registerFeature, registerSlot } from '../registry'
import './i18n'

/**
 * E2 subscription feature: SC2 first-run welcome (/welcome), the owner Subscription screen (/subscription,
 * repeated under Settings) and the SC14 "Cohort and subscriptions" DET tab.
 */
registerFeature(
  [
    { path: '/welcome', element: lazy(() => import('./Welcome')), permission: 'subscription.view', scope: 'company' },
    { path: '/subscription', element: lazy(() => import('./SubscriptionPage')), permission: 'subscription.view', scope: 'company' },
  ],
  [{ path: '/subscription', labelKey: 'subscription:nav.subscription', icon: '◈', permission: 'subscription.view', scope: 'company', order: 55 }],
)
registerSlot('det.tabs', { id: 'cohort-subscriptions', labelKey: 'subscription:det.tab', element: lazy(() => import('./CohortTab')), permission: 'det.cohort.view', order: 15 })
