import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Dialog, Empty, Message, Panel, Skeleton } from '../../components/ui'
import { ApiError, del, get, patch, post } from '../../lib/api'
import { formatDate, formatDateTime } from '../../lib/format'
import AddDelegateDialog from './AddDelegateDialog'
import { RightsSummary, RightsToggles } from './RightsToggles'
import type { Change, DelegatesResponse, Person, Quarantined, Toggle } from './types'

type Notice = { kind: 'info' | 'error' | 'success'; text: string }

/** SC11 team tab: people list (table desktop / cards mobile), invite, edit, suspend, remove, quarantine prompt, recent access changes. */
export default function TeamTab({ companyId }: { companyId: string }) {
  const { t, i18n } = useTranslation('settings')
  const { me, company } = useAuth()
  const [data, setData] = useState<DelegatesResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [editing, setEditing] = useState<Person | null>(null)
  const [removing, setRemoving] = useState<Person | null>(null)
  const noticeRef = useRef<HTMLDivElement>(null)
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'

  const load = useCallback(async () => {
    try {
      setData(await get<DelegatesResponse>(`/api/companies/${companyId}/delegates`))
      setErr(null)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message)
    }
  }, [companyId])
  useEffect(() => {
    load()
  }, [load])
  useEffect(() => {
    if (notice) noticeRef.current?.focus()
  }, [notice])

  if (err) return <Message kind="error">{err}</Message>
  if (!data) return <Skeleton rows={4} />

  const companyName = company ? (lang === 'ar' ? company.trade_name_ar : company.trade_name_en) : ''
  const auth = data.authority
  const isOwnerView = data.scope === 'all'
  const refusal = (e: unknown, fallback: string) => {
    const code = e instanceof ApiError ? e.code : ''
    if (code === 'LEVEL_TOO_LOW_FOR_ACTION') return t('reauth_failed')
    if (code === 'NO_PERMISSION' || code === 'OWNER_ONLY') return t('owner_only')
    if (code === 'RIGHT_SWITCHED_OFF') return t('locked')
    if (code === 'COMPANY_ON_HOLD') return t('on_hold')
    if (code === 'DET_DATA_STALE') return t('stale')
    return fallback
  }
  const act = async (fn: () => Promise<unknown>, ok: string, fallback: string) => {
    try {
      await fn()
      setNotice({ kind: 'success', text: ok })
      await load()
    } catch (e) {
      setNotice({ kind: 'error', text: refusal(e, fallback) })
    }
  }
  const chipTone = (c: Person['chip']) => (c === 'active' ? 'ok' : c === 'pending' ? 'attention' : c === 'suspended' ? 'urgent' : 'neutral')
  const rightsText = (p: Person) => (p.role === 'delegate' ? p.toggles.map((x) => t(`fn_${x}`)).join(', ') || t('off') : t('roles.owner', { ns: 'translation' }))
  const nameOf = (p: Person) => p.display_name || '—'

  const notices = (
    <>
      {notice && (
        <div ref={noticeRef} tabIndex={-1}>
          <Message kind={notice.kind}>{notice.text}</Message>
        </div>
      )}
      {auth.hold_state === 'no_owner' && isOwnerView && (
        <Panel tone="warning" title={t('no_owner_title')} id="no-owner">
          <p>{t('no_owner')}</p>
          <p><strong>{t('no_owner_next')}</strong></p>
        </Panel>
      )}
      {auth.hold_state === 'no_owner' && !isOwnerView && <Message kind="warning">{t('no_owner_delegate')}</Message>}
      {auth.hold_state === 'signatory_change_hold' && <Message kind="warning">{t('on_hold')}{auth.det_operations_alerted_at && <div>{t('on_hold_alerted')}</div>}</Message>}
      {auth.stale && <Message kind="warning">{t('stale')} <span className="muted">({t('last_updated')}: {auth.det_refreshed_at ? formatDateTime(auth.det_refreshed_at, lang) : '—'})</span></Message>}
    </>
  )

  if (!isOwnerView) {
    const own = data.own
    const self = data.people[0]
    return (
      <div>
        {notices}
        <Panel title={t('own_title')} id="own-rights">
          <p><strong><bdi>{companyName}</bdi></strong> {self && <Chip tone={chipTone(self.chip)}>{t(`chip_${self.chip}`)}</Chip>} {self?.authority_label && <Chip tone="urgent">{t('suspended_authority_changed')}</Chip>}</p>
          <p className="helper">{t('own_body')}</p>
          {own && <RightsToggles value={own.toggles} meta={data.toggles} readOnly />}
          <p className="helper">{t('delegate_refused_own')}</p>
        </Panel>
        {data.recent_changes.length > 0 && <RecentChanges changes={data.recent_changes} lang={lang} />}
      </div>
    )
  }

  const delegates = data.people.filter((p) => p.role === 'delegate')
  const owners = data.people.filter((p) => p.role !== 'delegate')
  const byDelegate = groupQuarantine(data.quarantine)
  const canManage = auth.hold_state === 'none' && !auth.stale && me?.det_match_result === 'matched'

  return (
    <div>
      {notices}
      {byDelegate.map((g) => (
        <Panel key={g.identity} tone="warning" title={t('quarantine_title')} id={`q-${g.identity}`}>
          <p>{t('drafts_on_hold', { n: g.items.length, name: g.name })}</p>
          <ul>
            {g.items.map((q) => (
              <li key={q.id} style={{ marginBottom: 8 }}>
                <bdi dir="ltr" className="ident">{q.draft_ref}</bdi> · {q.draft_type} · <Chip tone="draft">{t('initiated_by_removed')}</Chip> {q.is_demo && <Chip tone="info">{t('status.demo_data', { ns: 'translation' })}</Chip>}
                <div className="actions">
                  <Button onClick={() => act(() => post(`/api/companies/${companyId}/delegates/quarantine/${q.id}/decide`, { decision: 'keep' }), t('q_decided'), t('save_failed'))}>{t('keep')}</Button>
                  <Button variant="secondary" onClick={() => act(() => post(`/api/companies/${companyId}/delegates/quarantine/${q.id}/decide`, { decision: 'reassign' }), t('q_decided'), t('save_failed'))}>{t('reassign')}</Button>
                  <Button variant="danger" onClick={() => act(() => post(`/api/companies/${companyId}/delegates/quarantine/${q.id}/decide`, { decision: 'discard' }), t('q_decided'), t('save_failed'))}>{t('discard')}</Button>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      ))}
      <Panel
        title={t('people')}
        id="people"
        actions={
          <>
            <span className="set-updated">{t('last_updated')}: <span className="nowrap">{formatDateTime(data.last_updated, lang)}</span></span>
            <Button variant="secondary" className="btn-sm" onClick={load}><Icon name="history" size={16} />{t('refresh')}</Button>
            <Button onClick={() => setInviteOpen(true)} disabled={!canManage} title={!canManage ? (auth.hold_state !== 'none' ? t('on_hold') : auth.stale ? t('stale') : t('no_owner')) : undefined}>{t('invite')}</Button>
          </>
        }
      >
        {!canManage && <p className="helper">{auth.hold_state !== 'none' ? t('on_hold') : auth.stale ? t('stale') : t('no_owner')}</p>}
        <p className="set-statement"><Icon name="info" size={16} /><span>{t('statement')}</span></p>
        {delegates.length === 0 && <Empty icon="users" title={t('empty')} action={<Button onClick={() => setInviteOpen(true)} disabled={!canManage}>{t('invite')}</Button>} />}
        <ul className="set-people" aria-label={t('people')}>
          {[...owners, ...delegates].map((p) => (
            <li key={p.id} className="set-person">
              <span className={`set-avatar ${p.role === 'delegate' ? 'is-delegate' : ''}`} aria-hidden="true">{initial(nameOf(p))}</span>
              <div className="set-person-main">
                <div className="set-person-name">
                  <strong><bdi>{nameOf(p)}</bdi></strong>
                  <span className="set-role">{t(`roles.${p.role}`, { ns: 'translation' })}</span>
                  <Chip tone={chipTone(p.chip)}>{t(`chip_${p.chip}`)}</Chip>
                  {p.authority_label && <Chip tone="urgent">{t('suspended_authority_changed')}</Chip>}
                </div>
                <div className="set-person-meta">
                  <span>{t('col_rights')}: <span className="set-rights">{rightsText(p)}</span></span>
                  <span className="nowrap">{t('col_since')}: {formatDate(p.granted_at, lang)}</span>
                </div>
                {p.name_differs && <div className="notice-tbc">{t('name_differs')}</div>}
                {p.dormant_flag && <div className="notice-tbc">{t('dormant')}</div>}
                {p.kind === 'invitation' && p.chip === 'pending' && <div className="helper">{t('pending_waiting', { name: nameOf(p) })}</div>}
              </div>
              {p.role === 'delegate' && (
                <div className="set-person-actions">
                  <RowActions p={p} canManage={canManage} onEdit={() => setEditing(p)} onRemove={() => setRemoving(p)} onAct={act} companyId={companyId} />
                </div>
              )}
            </li>
          ))}
        </ul>
      </Panel>
      <RecentChanges changes={data.recent_changes} lang={lang} />
      <AddDelegateDialog key={String(inviteOpen)} open={inviteOpen} companyId={companyId} meta={data.toggles} onClose={() => setInviteOpen(false)} onDone={(msg) => { setNotice({ kind: 'success', text: msg }); load() }} />
      {editing && <EditRightsDialog p={editing} companyId={companyId} meta={data.toggles} onClose={() => setEditing(null)} onDone={(name) => { setEditing(null); setNotice({ kind: 'success', text: t('rights_updated', { name }) }); load() }} onError={(m) => setNotice({ kind: 'error', text: m })} refusal={refusal} />}
      {removing && (
        <Dialog open title={t('remove_title', { name: nameOf(removing) })} onClose={() => setRemoving(null)} labelledBy="remove-title">
          <p>{t('remove_body')}</p>
          <div className="dialog-actions">
            <Button variant="secondary" onClick={() => setRemoving(null)}>{t('common.cancel', { ns: 'translation' })}</Button>
            <Button variant="danger" onClick={() => { const p = removing; setRemoving(null); act(() => del(`/api/companies/${companyId}/delegates/${p.id}`), t('delegate_removed'), t('changes_not_saved')) }}>{t('remove')}</Button>
          </div>
        </Dialog>
      )}
    </div>
  )
}

function RowActions({ p, canManage, onEdit, onRemove, onAct, companyId }: { p: Person; canManage: boolean; onEdit: () => void; onRemove: () => void; onAct: (fn: () => Promise<unknown>, ok: string, fallback: string) => Promise<void>; companyId: string }) {
  const { t } = useTranslation('settings')
  if (p.kind === 'invitation') {
    if (p.status !== 'pending' && p.status !== 'expired') return null
    return (
      <div className="set-row-actions">
        <Button variant="secondary" className="btn-sm" disabled={!canManage} onClick={() => onAct(() => post(`/api/companies/${companyId}/delegates/invitations/${p.id}/resend`), t('invited_ok'), t('invite_failed'))}>{t('resend')}</Button>
        {p.status === 'pending' && <Button variant="link" disabled={!canManage} onClick={() => onAct(() => post(`/api/companies/${companyId}/delegates/invitations/${p.id}/withdraw`), t('delegate_removed'), t('changes_not_saved'))}>{t('withdraw')}</Button>}
      </div>
    )
  }
  if (p.chip === 'removed') return null
  return (
    <div className="set-row-actions">
      <Button variant="secondary" className="btn-sm" disabled={!canManage} onClick={onEdit}>{t('edit_rights')}</Button>
      {p.status === 'active' && <Button variant="secondary" className="btn-sm" disabled={!canManage} onClick={() => onAct(() => post(`/api/companies/${companyId}/delegates/${p.id}/suspend`), t('rights_updated', { name: p.display_name || '' }), t('changes_not_saved'))}>{t('suspend')}</Button>}
      {p.status === 'suspended' && <Button variant="secondary" className="btn-sm" disabled={!canManage} onClick={() => onAct(() => post(`/api/companies/${companyId}/delegates/${p.id}/reinstate`), t('rights_updated', { name: p.display_name || '' }), t('changes_not_saved'))}>{t('reinstate')}</Button>}
      <Button variant="danger" className="btn-sm" disabled={!canManage} onClick={onRemove}>{t('remove')}</Button>
    </div>
  )
}

function EditRightsDialog({ p, companyId, meta, onClose, onDone, onError, refusal }: { p: Person; companyId: string; meta: DelegatesResponse['toggles']; onClose: () => void; onDone: (name: string) => void; onError: (m: string) => void; refusal: (e: unknown, fallback: string) => string }) {
  const { t } = useTranslation('settings')
  const [value, setValue] = useState<Toggle[]>(p.toggles)
  const [confirm, setConfirm] = useState(false)
  const [saving, setSaving] = useState(false)
  const name = p.display_name || '—'
  const save = async () => {
    setSaving(true)
    try {
      await patch(`/api/companies/${companyId}/delegates/${p.id}`, { toggles: value })
      onDone(name)
    } catch (e) {
      onError(refusal(e, t('save_failed')))
      onClose()
    } finally {
      setSaving(false)
    }
  }
  return (
    <Dialog open title={t('edit_title', { name })} onClose={onClose} labelledBy="edit-title">
      <p className="helper">{t('edit_body')}</p>
      {!confirm ? (
        <>
          <RightsToggles value={value} onChange={setValue} meta={meta} />
          <div className="dialog-actions"><Button variant="secondary" onClick={onClose}>{t('common.cancel', { ns: 'translation' })}</Button><Button onClick={() => setConfirm(true)}>{t('common.next', { ns: 'translation' })}</Button></div>
        </>
      ) : (
        <>
          <RightsSummary value={value} />
          <div className="dialog-actions" aria-live="polite">
            <Button variant="secondary" onClick={() => setConfirm(false)} disabled={saving}>{t('common.back', { ns: 'translation' })}</Button>
            <Button onClick={save} disabled={saving}>{saving ? t('common.saving', { ns: 'translation' }) : t('confirm_rights')}</Button>
          </div>
        </>
      )}
    </Dialog>
  )
}

function RecentChanges({ changes, lang }: { changes: Change[]; lang: string }) {
  const { t } = useTranslation('settings')
  return (
    <Panel title={t('recent_changes')} id="recent-changes">
      {changes.length === 0 ? <p className="muted">{t('common.none', { ns: 'translation' })}</p> : (
        <ol className="set-changes">
          {changes.map((c) => (
            <li key={c.id}>
              <span className="set-change-dot" aria-hidden="true" />
              <div className="set-change-main">
                <span className="set-change-title">{t(`change.${c.change_type}`, { defaultValue: c.change_type.replace(/_/g, ' ') })} · <bdi>{c.delegate_label || '—'}</bdi></span>
                {c.changed_by_name && <span className="set-change-by">{t('by', { name: '' })}<bdi>{c.changed_by_name}</bdi>{c.changed_by_role && <> ({t(`roles.${c.changed_by_role}`, { ns: 'translation', defaultValue: c.changed_by_role })})</>}</span>}
              </div>
              <time className="set-change-time" dateTime={c.changed_at}>{formatDateTime(c.changed_at, lang)}</time>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}

function initial(name: string) {
  const ch = name.trim().charAt(0)
  return ch && ch !== '—' ? ch.toUpperCase() : '?'
}

function groupQuarantine(items: Quarantined[]) {
  const map = new Map<string, { identity: string; name: string; items: Quarantined[] }>()
  for (const q of items) {
    const g = map.get(q.delegate_identity_uuid) ?? { identity: q.delegate_identity_uuid, name: q.delegate_name || '—', items: [] }
    g.items.push(q)
    map.set(q.delegate_identity_uuid, g)
  }
  return [...map.values()]
}
