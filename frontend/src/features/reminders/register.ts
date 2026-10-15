import { lazy } from 'react'
import { registerSlot } from '../registry'
import './i18n'

// SC11 'Reminders' settings tab and the SC3 in-portal reminder inbox panel (E3-S4).
registerSlot('settings.tabs', { id: 'reminders', labelKey: 'reminders:tab', element: lazy(() => import('./ReminderSettings')), permission: 'reminders.view', order: 20 })
registerSlot('dashboard.panels', { id: 'reminders-inbox', labelKey: 'reminders:inbox_title', element: lazy(() => import('./InboxPanel')), permission: 'reminders.view', order: 30 })
