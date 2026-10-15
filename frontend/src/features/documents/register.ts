import { lazy } from 'react'
import { registerFeature } from '../registry'
import './i18n'

registerFeature(
  [{ path: '/documents', element: lazy(() => import('./DocumentPack')), permission: 'documents.view', scope: 'company' }],
  [{ path: '/documents', labelKey: 'nav.documents', icon: '📄', permission: 'documents.view', scope: 'company', order: 35 }],
)
