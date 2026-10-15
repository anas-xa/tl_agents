import { useTranslation } from 'react-i18next'
import { Panel } from '../../components/ui'
import LinkStatusList from './LinkStatusList'

/** SC3 'Data links' panel (E4-S6): compact link status list, worst first. */
export default function DashboardPanel() {
  const { t } = useTranslation('consent')
  return (
    <Panel title={t('links_title')}>
      <LinkStatusList compact />
    </Panel>
  )
}
