import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Placeholder } from '../../components/Placeholder'
import { Chip, PageHeader, Tabs } from '../../components/ui'
import Books from './Books'
import CalculationPanel from './CalculationPanel'
import DraftsList from './DraftsList'
import './tax.css'

const TABS = ['books', 'vat', 'ct', 'drafts'] as const
type Tab = (typeof TABS)[number]

/** SC6 Tax workspace: books and calculations (E5-S1, E5-S2) plus the list of draft returns (E5-S3). */
export default function TaxWorkspace() {
  const { t, i18n } = useTranslation('tax')
  const { companyId, company, can } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (TABS as readonly string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as Tab) : 'books'
  if (!companyId) return <Placeholder variant="C" />
  const tabs = TABS.filter((x) => x !== 'drafts' || can('returns.view'))
  const label: Record<Tab, string> = { books: t('tab_books'), vat: t('tab_vat'), ct: t('tab_ct'), drafts: t('tab_drafts') }
  const companyName = company ? (i18n.language.startsWith('ar') ? company.trade_name_ar : company.trade_name_en) : null
  return (
    <div className="page tax-page">
      <PageHeader
        eyebrow={companyName ? <bdi>{companyName}</bdi> : t('product_name')}
        title={t('title')}
        subtitle={t('subtitle')}
        meta={
          <>
            <span>{t('product_name')}</span>
            <Chip tone="neutral">{t('draft_label')}</Chip>
          </>
        }
      />
      <Tabs
        tabs={tabs.map((x) => ({ id: x, label: label[x] }))}
        value={tab}
        onChange={(x) => setParams({ tab: x })}
        label={t('title')}
        idPrefix="tab"
      />
      <section role="tabpanel" id={`tab-${tab}-panel`} aria-labelledby={`tab-${tab}`}>
        {tab === 'books' && <Books companyId={companyId} />}
        {tab === 'vat' && <CalculationPanel key={`vat-${companyId}`} companyId={companyId} taxType="vat" />}
        {tab === 'ct' && <CalculationPanel key={`ct-${companyId}`} companyId={companyId} taxType="ct" />}
        {tab === 'drafts' && <DraftsList companyId={companyId} />}
      </section>
      <p className="hint tax-foot">{t('information_only')}</p>
    </div>
  )
}
