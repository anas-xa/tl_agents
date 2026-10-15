import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Chip, Message, Panel, Skeleton, Table } from '../../components/ui'
import { formatDate } from '../../lib/format'
import { get } from '../../lib/api'

interface ConfigRow { key: string; version: number; value: unknown; unit: string | null; owner: string; status: string; label: string | null; effective_from: string }
interface RuleRow { rule_id: string; version: string; title: string; instrument: string | null; status: string; confirmed_by: string | null; effective_from: string | null; owner_role: string | null }

/** Configuration and rule-version registers (read view). Changes are made through the API with a reason and, where required, a second approver. */
export default function ConfigRegister() {
  const { t, i18n } = useTranslation()
  const [config, setConfig] = useState<ConfigRow[] | null>(null)
  const [rules, setRules] = useState<RuleRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<'config' | 'rules'>('config')
  useEffect(() => {
    Promise.all([get<ConfigRow[]>('/api/admin/config'), get<RuleRow[]>('/api/admin/rules')]).then(([c, r]) => { setConfig(c); setRules(r) }).catch((e) => setErr(e.message))
  }, [])
  const tone = (s: string) => (s === 'confirmed' ? 'ok' : s === 'provisional' ? 'attention' : 'urgent')
  return (
    <div>
      <h1>{t('nav.admin')}</h1>
      {err && <Message kind="error">{err}</Message>}
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'config'} onClick={() => setTab('config')}>Configuration register</button>
        <button role="tab" aria-selected={tab === 'rules'} onClick={() => setTab('rules')}>Rule-version register</button>
      </div>
      {tab === 'config' && (
        <Panel title="Configuration register">
          {!config ? <Skeleton /> : (
            <Table headers={['Key', 'Value', 'Unit', 'Owner', 'Status', 'Effective', 'Version']}>
              {config.map((r) => (
                <tr key={r.key}>
                  <td><bdi dir="ltr">{r.key}</bdi></td>
                  <td><code dir="ltr">{JSON.stringify(r.value)}</code></td>
                  <td>{r.unit}</td>
                  <td>{r.owner}</td>
                  <td><Chip tone={tone(r.status)}>{r.status.replace(/_/g, ' ')}</Chip>{r.label && <div className="notice-tbc">{r.label}</div>}</td>
                  <td>{formatDate(r.effective_from, i18n.language)}</td>
                  <td>v{r.version}</td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
      )}
      {tab === 'rules' && (
        <Panel title="Rule-version register">
          {!rules ? <Skeleton /> : (
            <Table headers={['Rule', 'Version', 'Title', 'Instrument', 'Effective', 'Confirmed by', 'Status', 'Owner']}>
              {rules.map((r) => (
                <tr key={r.rule_id}>
                  <td><bdi dir="ltr">{r.rule_id}</bdi></td>
                  <td>{r.version}</td>
                  <td>{r.title}</td>
                  <td>{r.instrument}</td>
                  <td>{formatDate(r.effective_from, i18n.language)}</td>
                  <td>{r.confirmed_by ?? '—'}</td>
                  <td><Chip tone={tone(r.status)}>{r.status.replace(/_/g, ' ')}</Chip></td>
                  <td>{r.owner_role}</td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
      )}
    </div>
  )
}
