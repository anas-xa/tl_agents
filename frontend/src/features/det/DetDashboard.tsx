import { Suspense, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useSlotEntries } from '../../components/Slot'
import { Chip, Empty, Skeleton } from '../../components/ui'

/**
 * SC14 DET admin dashboard: a tabbed page that renders every `det.tabs` slot entry (cohort, escalations,
 * delegation overview, KPIs from other features; residency, phases, integrations, availability from here).
 * Aggregates only: no company-level financial data is ever rendered on this page.
 */
export default function DetDashboard() {
  const { t } = useTranslation('det')
  const entries = useSlotEntries('det.tabs')
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<string>(params.get('tab') || entries[0]?.id || '')
  useEffect(() => {
    if (!entries.some((e) => e.id === tab) && entries[0]) setTab(entries[0].id)
  }, [entries, tab])
  const active = entries.find((e) => e.id === tab)
  const Active = active?.element as React.ComponentType | undefined
  return (
    <div className="page">
      <h1>{t('title')}</h1>
      <p>
        {t('intro')} <Chip tone="info">{t('pilot_data')}</Chip>
      </p>
      {entries.length === 0 ? (
        <Empty title={t('not_yet_available')} />
      ) : (
        <>
          <div className="tabs" role="tablist" aria-label={t('title')}>
            {entries.map((e) => (
              <button key={e.id} role="tab" id={`det-tab-${e.id}`} aria-selected={tab === e.id} aria-controls={`det-panel-${e.id}`} onClick={() => { setTab(e.id); setParams({ tab: e.id }, { replace: true }) }}>
                {t(e.labelKey.includes(':') ? e.labelKey : `det:${e.labelKey}`)}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`det-panel-${tab}`} aria-labelledby={`det-tab-${tab}`}>
            {Active && (
              <Suspense fallback={<Skeleton rows={4} />}>
                <Active />
              </Suspense>
            )}
          </div>
        </>
      )}
    </div>
  )
}
