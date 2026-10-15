import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/auth'
import { Slot, useSlotEntries } from '../../components/Slot'
import { Button, Chip, Field, Ident, Message, Panel, Skeleton } from '../../components/ui'
import { ApiError, post } from '../../lib/api'
import { bl, useFetch, type SubscriptionView } from './lib'
import { FeeCard, Proposed, StatusBadge, TermsSheet } from './parts'

interface WelcomeData {
  welcome: { status: 'pending' | 'done' | 'later'; language_choice: string | null; reminder_channel: string | null; terms_version_shown: string; notice_version_shown: string }
  reminder_channels: Record<string, boolean>
  subscription: SubscriptionView
}

/**
 * SC2 Subscription and first-run welcome. Shown once, then reachable from the Subscription page. Shows the
 * Phase 1 modules only, the example fee, versions, the owner's choices (language, reminder channel stub) and the
 * set-up checklist other features contribute through the `welcome.checklist` slot. "Do it later" never blocks.
 */
export default function Welcome() {
  const { t, i18n } = useTranslation('subscription')
  const { companyId, company, setLanguage } = useAuth()
  const nav = useNavigate()
  const heading = useRef<HTMLHeadingElement>(null)
  const { data, error, loading, slow, reload } = useFetch<WelcomeData>(companyId ? `/api/companies/${companyId}/welcome` : null, [companyId])
  const [langChoice, setLang] = useState<string | null>(null)
  const [channelChoice, setChannel] = useState<string | null>(null)
  const [termsOpen, setTermsOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const checklist = useSlotEntries('welcome.checklist')

  useEffect(() => {
    heading.current?.focus()
  }, [])

  if (!companyId) return null
  if (loading && !data) {
    return (
      <div className="page" aria-busy="true">
        <p role="status">{t('screen.loading')}</p>
        <Skeleton rows={6} />
        {slow && <Message kind="info">{t('screen.still_loading')} <Button variant="link" onClick={reload}>{t('screen.try_again')}</Button></Message>}
      </div>
    )
  }
  if (error && !data) {
    return (
      <div className="page">
        <Message kind="error">
          {t('screen.error')} {error instanceof ApiError && error.reference && <Ident>{error.reference}</Ident>}
          <div className="actions"><Button onClick={reload}>{t('screen.try_again')}</Button></div>
        </Message>
      </div>
    )
  }
  if (!data) return null
  const view = data.subscription
  // The owner's earlier choice is shown until they pick again (derived, not mirrored into state).
  const lang = langChoice ?? data.welcome.language_choice ?? (i18n.language.startsWith('ar') ? 'ar' : 'en')
  const channel = channelChoice ?? data.welcome.reminder_channel ?? 'portal'
  const owner = view.can_change || view.role === 'remote_owner'
  const firstSub = view.licences.find((l) => l.subscription)?.subscription ?? null
  const tradeName = company ? (i18n.language.startsWith('ar') ? company.trade_name_ar : company.trade_name_en) : ''

  const finish = async (action: 'done' | 'later') => {
    setSending(true)
    setErr(null)
    try {
      await post(`/api/companies/${companyId}/welcome`, { action, language_choice: owner ? lang : null, reminder_channel: owner ? channel : null })
      if (owner && action === 'done' && lang !== i18n.language) await setLanguage(lang as 'ar' | 'en')
      nav('/subscription')
    } catch (e) {
      setErr(`${t('screen.error')}${e instanceof ApiError && e.reference ? ` (${e.reference})` : ''}`)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="page">
      <p className="hint"><bdi>{tradeName}</bdi></p>
      <h1 ref={heading} tabIndex={-1}>{t('welcome.title')}</h1>
      <p>{t('welcome.intro')}<Proposed /></p>
      {!owner && <Message kind="info">{t('screen.only_owner')}</Message>}

      {firstSub ? (
        <Panel title={<>{t('screen.licence')} <Ident>{firstSub.licence_number}</Ident> <StatusBadge badge={firstSub.badge} /></>} id="welcome-sub">
          <FeeCard sub={firstSub} />
        </Panel>
      ) : (
        <Message kind="info">{view.licences.some((l) => l.empty_state === 'in_cohort_no_event') ? t('screen.empty_in_cohort') : t('screen.empty_not_in_pilot')}</Message>
      )}

      <Panel title={t('welcome.included')} id="welcome-included">
        <ul>{view.included.map((m) => <li key={m.code}>{bl(m, i18n.language)}</li>)}</ul>
        <h3>{t('welcome.not_included')}</h3>
        <ul>{view.not_included.map((m) => <li key={m.code}>{bl(m, i18n.language)}</li>)}</ul>
        <p>{t('welcome.audit_note')}<Proposed /></p>
        <p>{t('welcome.audit_other')}</p>
        <p className="hint">
          {t('welcome.terms_version', { v: data.welcome.terms_version_shown })} · {t('welcome.notice_version', { v: data.welcome.notice_version_shown })} ·{' '}
          <Button variant="link" onClick={() => setTermsOpen(true)}>{t('screen.see_terms')}</Button>
        </p>
      </Panel>

      {owner && (
        <Panel title={t('welcome.reminder')} id="welcome-choices">
          <fieldset>
            <legend>{t('welcome.language')}</legend>
            {(['ar', 'en'] as const).map((l) => (
              <label key={l} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', minHeight: 44, marginInlineEnd: 16 }} lang={l}>
                <input type="radio" name="welcome-lang" value={l} checked={lang === l} onChange={() => setLang(l)} /> {l === 'ar' ? 'العربية' : 'English'}
              </label>
            ))}
          </fieldset>
          <Field label={t('welcome.reminder')} id="welcome-channel" hint={t('welcome.reminder_stub')}>
            <select id="welcome-channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="portal">{t('welcome.reminder_portal')}</option>
              <option value="email" disabled={data.reminder_channels.email === false}>{t('welcome.reminder_email')}</option>
              <option value="sms" disabled={data.reminder_channels.sms === false}>{t('welcome.reminder_sms')}</option>
            </select>
          </Field>
        </Panel>
      )}

      <Panel title={t('welcome.checklist')} id="welcome-checklist">
        {checklist.length === 0 ? <p className="hint">{t('welcome.checklist_empty')}</p> : <Slot name="welcome.checklist" />}
      </Panel>

      {data.welcome.status !== 'pending' && <p><Chip tone="info">{data.welcome.status === 'done' ? t('welcome.done') : t('welcome.later')}</Chip> {t('welcome.resume')}</p>}
      {err && <Message kind="error">{err}</Message>}
      <div className="actions">
        <Button disabled={sending} onClick={() => finish('done')}>{sending ? t('screen.sending') : t('welcome.done')}</Button>
        <Button variant="secondary" disabled={sending} onClick={() => finish('later')}>{t('welcome.later')}</Button>
      </div>
      <p className="hint">{t('welcome.resume')}</p>
      <TermsSheet companyId={companyId} open={termsOpen} onClose={() => setTermsOpen(false)} />
    </div>
  )
}
