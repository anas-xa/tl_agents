import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useSlotEntries } from '../../components/Slot'
import { Chip, Empty, PageHeader, Skeleton, Tabs } from '../../components/ui'
import { DetHeaderMetaContext } from './headerMeta'
import './det.css'

/**
 * SC14 DET admin dashboard: a tabbed page that renders every `det.tabs` slot entry (cohort, escalations,
 * delegation overview, KPIs from other features; residency, phases, integrations, availability from here).
 * Aggregates only: no company-level financial data is ever rendered on this page.
 * A tab may place its provenance line (demo data, minimum group size, data as of) in the header meta row.
 */
export default function DetDashboard() {
  const { t } = useTranslation('det')
  const entries = useSlotEntries('det.tabs')
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<string>(params.get('tab') || entries[0]?.id || '')
  const [meta, setMeta] = useState<ReactNode>(null)
  useEffect(() => {
    if (!entries.some((e) => e.id === tab) && entries[0]) setTab(entries[0].id)
  }, [entries, tab])
  const active = entries.find((e) => e.id === tab)
  const Active = active?.element as React.ComponentType | undefined
  return (
    <div className="page det-page">
      <PageHeader
        eyebrow={t('eyebrow')}
        title={t('title')}
        subtitle={t('intro')}
        meta={
          <>
            <Chip tone="info">{t('pilot_data')}</Chip>
            {meta}
          </>
        }
      />
      {entries.length === 0 ? (
        <Empty icon="grid" title={t('not_yet_available')} />
      ) : (
        <>
          <Tabs
            label={t('tabs_label')}
            idPrefix="det-tab"
            value={tab}
            onChange={(id) => { setTab(id); setParams({ tab: id }, { replace: true }) }}
            tabs={entries.map((e) => ({ id: e.id, label: t(e.labelKey.includes(':') ? e.labelKey : `det:${e.labelKey}`) }))}
          />
          <div role="tabpanel" className="det-tabpanel" id={`det-tab-${tab}-panel`} aria-labelledby={`det-tab-${tab}`}>
            <DetHeaderMetaContext.Provider value={setMeta}>
              {Active && (
                <Suspense fallback={<Skeleton rows={4} />}>
                  <Active />
                </Suspense>
              )}
            </DetHeaderMetaContext.Provider>
          </div>
        </>
      )}
    </div>
  )
}
