import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Button, Chip, Message, Panel, Skeleton } from '../../components/ui'
import { formatDate } from '../../lib/format'
import { useBi, useFetch, type Bi } from './lib'

interface LinkRow { group: string; label: Bi; status: 'linked' | 'pending' | 'missing' | 'not_started'; chip: Bi; via_manual: boolean; pending_message?: Bi | null; action_enabled: boolean; action_reason?: Bi | null }
interface K12 { state: string; message: Bi | null; window_start: string | null; window_end: string | null; days_left: number | null; links: LinkRow[]; buttons: Bi[]; based_on_incomplete_data: boolean; complete_via_manual_path_only: boolean; viewer_role: 'owner' | 'delegate' }

/** SC2 first-run / SC3 card: K12 setup checklist with Linked / Pending / Missing chips, window date and days left. */
export default function K12Checklist() {
  const { t, i18n } = useTranslation('det')
  const { tx } = useBi()
  const { companyId } = useAuth()
  const nav = useNavigate()
  const { data, error, loading, reload } = useFetch<K12>(companyId ? `/api/companies/${companyId}/k12` : null, [companyId])
  if (loading && !data) return <Panel title={t('k12_title')}><Skeleton rows={3} /></Panel>
  if (error && !data) return <Panel title={t('k12_title')}><Message kind="error">{t('k12_error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message></Panel>
  if (!data) return null
  const chipTone = (s: LinkRow['status']) => (s === 'linked' ? 'ok' : s === 'pending' ? 'attention' : s === 'missing' ? 'urgent' : 'neutral')
  const chipIcon = (s: LinkRow['status']) => (s === 'linked' ? '✓' : s === 'pending' ? '◔' : s === 'missing' ? '!' : '○')
  const isDelegate = data.viewer_role === 'delegate'
  const routeFor = (g: string) => (g === 'det_licence_record' ? '/welcome?licence=manual' : g === 'fta_tax_profile' ? '/tax?profile=1' : '/consent')
  return (
    <Panel title={t('k12_title')} id="k12-checklist">
      {data.state === 'not_started' && data.message && <Message kind="info">{tx(data.message)}</Message>}
      {data.state === 'exited' && <Message kind="info">{t('k12_exited')}</Message>}
      {data.state === 'expired_missing' && data.message && <Message kind="warning">{tx(data.message)}</Message>}
      {data.state === 'complete' && <Message kind="success">{t('k12_complete')} {data.complete_via_manual_path_only && <Chip tone="draft">{t('k12_complete_manual')}</Chip>}</Message>}
      {data.window_end && data.state === 'window_open' && (
        <p>
          {t('k12_window')}: {t('k12_window_ends', { date: formatDate(data.window_end, i18n.language) })} · {t(data.days_left === 1 ? 'k12_days_left_one' : 'k12_days_left_other', { count: data.days_left ?? 0 })}
        </p>
      )}
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {data.links.map((l) => (
          <li key={l.group} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', minHeight: 44 }}>
            <Chip tone={chipTone(l.status)} icon={chipIcon(l.status)}>{tx(l.chip)}</Chip>
            <span>{tx(l.label)}</span>
            {l.via_manual && l.status === 'linked' && <Chip tone="draft">{t('wl_manual_label')}</Chip>}
            {l.pending_message && <span className="hint">{tx(l.pending_message)}</span>}
            {l.status === 'pending' && !isDelegate && l.pending_message?.en.startsWith('Waiting for the owner') && <Button variant="secondary" onClick={() => nav('/consent')}>{t('k12_consent_centre')}</Button>}
            {(l.status === 'missing' || l.status === 'pending') && data.state !== 'not_started' && (
              isDelegate ? <Button variant="secondary" disabled={l.status === 'pending'}>{t('k12_ask_owner')}</Button> : <Button variant="secondary" onClick={() => nav(routeFor(l.group))}>{t('k12_link_now')}</Button>
            )}
            {l.status === 'not_started' && <Button variant="secondary" disabled title={l.action_reason ? tx(l.action_reason) : undefined}>{isDelegate ? t('k12_ask_owner') : t('k12_link_now')}</Button>}
          </li>
        ))}
      </ul>
      {data.based_on_incomplete_data && data.state !== 'not_started' && <p><Chip tone="attention">{t('k12_based_on_incomplete')}</Chip></p>}
    </Panel>
  )
}
