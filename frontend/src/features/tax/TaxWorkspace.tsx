import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Placeholder } from '../../components/Placeholder'
import { Chip } from '../../components/ui'
import Books from './Books'
import CalculationPanel from './CalculationPanel'
import DraftsList from './DraftsList'

const TABS = ['books', 'vat', 'ct', 'drafts'] as const
type Tab = (typeof TABS)[number]

/** SC6 Tax workspace: books and calculations (E5-S1, E5-S2) plus the list of draft returns (E5-S3). */
export default function TaxWorkspace() {
  const { t } = useTranslation('tax')
  const { companyId, can } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (TABS as readonly string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as Tab) : 'books'
  if (!companyId) return <Placeholder variant="C" />
  const tabs = TABS.filter((x) => x !== 'drafts' || can('returns.view'))
  const label: Record<Tab, string> = { books: t('tab_books'), vat: t('tab_vat'), ct: t('tab_ct'), drafts: t('tab_drafts') }
  return (
    <div className="page">
      <header className="panel-header" style={{ paddingInline: 0 }}>
        <div>
          <h1>{t('title')}</h1>
          <p className="hint">{t('product_name')} · <Chip tone="neutral">{t('draft_label')}</Chip></p>
        </div>
      </header>
      <div role="tablist" aria-label={t('title')} className="actions">
        {tabs.map((x) => (
          <button
            key={x}
            role="tab"
            id={`tab-${x}`}
            aria-selected={tab === x}
            aria-controls={`panel-${x}`}
            className={`btn ${tab === x ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setParams({ tab: x })}
            onKeyDown={(e) => {
              const i = tabs.indexOf(x)
              if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                const dir = (e.key === 'ArrowRight') === (document.documentElement.dir !== 'rtl') ? 1 : -1
                const next = tabs[(i + dir + tabs.length) % tabs.length]
                setParams({ tab: next })
                document.getElementById(`tab-${next}`)?.focus()
              }
            }}
          >
            {label[x]}
          </button>
        ))}
      </div>
      <section role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} style={{ marginTop: 16 }}>
        {tab === 'books' && <Books companyId={companyId} />}
        {tab === 'vat' && <CalculationPanel key={`vat-${companyId}`} companyId={companyId} taxType="vat" />}
        {tab === 'ct' && <CalculationPanel key={`ct-${companyId}`} companyId={companyId} taxType="ct" />}
        {tab === 'drafts' && <DraftsList companyId={companyId} />}
      </section>
      <p className="hint">{t('information_only')}</p>
    </div>
  )
}
