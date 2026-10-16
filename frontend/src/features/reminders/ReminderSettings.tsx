import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Icon } from '../../components/Icon'
import { Button, Chip, Field, Message, Panel, Skeleton } from '../../components/ui'
import { put } from '../../lib/api'
import { formatDate } from '../../lib/format'
import { useFetch } from '../deadlines/lib'
import type { Prefs } from './types'
import '../settings/settings.css'

/** SC11 reminder settings: portal locked on; email (Phase 1B switch); SMS stored as recorded opt-in (Phase 1C, off);
 * WhatsApp shown off with its reason; language. Everyone edits only their own channels. */
export default function ReminderSettings() {
  const { t, i18n } = useTranslation('reminders')
  const { companyId } = useAuth()
  const { data, error, loading, reload } = useFetch<Prefs>(companyId ? `/api/companies/${companyId}/reminders/preferences` : null)
  const [form, setForm] = useState<{ email: boolean; sms: boolean; language: string }>({ email: false, sms: false, language: '' })
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  useEffect(() => {
    if (data) setForm({ email: data.channels.email, sms: data.channels.sms, language: data.language ?? '' })
  }, [data])
  if (loading && !data) return <Panel title={t('settings_title')}><p aria-busy="true">{t('loading')}</p><Skeleton rows={3} /></Panel>
  if (error && !data) return <Message kind="error">{t('error')} <Button variant="link" onClick={reload}>{t('try_again')}</Button></Message>
  if (!data) return null
  const st = data.channel_states
  const save = async () => {
    try {
      const out = await put<Prefs>(`/api/companies/${companyId}/reminders/preferences`, { channels: { email: form.email, sms: form.sms }, language: form.language || null, set_language: true })
      setForm({ email: out.channels.email, sms: out.channels.sms, language: out.language ?? '' })
      setMsg({ kind: 'success', text: t('saved') })
    } catch {
      setForm({ email: data.channels.email, sms: data.channels.sms, language: data.language ?? '' })
      setMsg({ kind: 'error', text: t('save_failed') })
    }
  }
  const sw = (id: string, label: string, checked: boolean, onChange: ((v: boolean) => void) | null, desc: string, extra?: React.ReactNode) => (
    <div className={`switch set-switch ${checked ? 'is-on' : ''}`} key={id}>
      <input id={id} className="set-toggle" type="checkbox" role="switch" aria-checked={checked} checked={checked} disabled={!onChange} aria-disabled={!onChange} aria-describedby={`${id}-desc`} onChange={(e) => onChange?.(e.target.checked)} />
      <div>
        <label htmlFor={id} className="set-switch-label">{label}</label>
        <div id={`${id}-desc`} className="desc">{desc} {extra}</div>
      </div>
      <span className="switch-state">{!onChange && id === 'ch-portal' && <Icon name="lock" size={14} />}{checked ? t('on') : t('off')}</span>
    </div>
  )
  return (
    <Panel title={t('settings_title')} className="set-reminders">
      <div aria-live="polite">{msg && <Message kind={msg.kind}>{msg.text}</Message>}</div>
      {data.role === 'delegate' && <p className="helper">{t('delegate_own')}</p>}
      {!st.email.enabled && <Message kind="info">{t('phase_note')}</Message>}
      <h3 className="set-rights-sub set-first">{t('channels')}</h3>
      {sw('ch-portal', t('channel.portal'), true, null, t('locked'))}
      {sw('ch-email', t('channel.email'), form.email, (v) => setForm({ ...form, email: v }), data.contacts.email ? `${t('contact')}: ${data.contacts.email}` : t('phase_note'),
        <>
          {data.contacts.email && !data.contacts.email_verified && <Chip tone="attention" icon="!">{t('unverified')}</Chip>}
          {data.contacts.email_state === 'undeliverable' && <Chip tone="critical" icon="✕">{t('not_delivered')}</Chip>}
        </>)}
      {sw('ch-sms', t('channel.sms'), form.sms, (v) => setForm({ ...form, sms: v }), st.sms.enabled ? '' : t('sms_note'), data.sms_opt_in_at ? <span>{t('sms_opt_in', { date: formatDate(data.sms_opt_in_at, i18n.language) })}</span> : null)}
      {sw('ch-whatsapp', t('channel.whatsapp'), false, null, t('whatsapp_off'))}
      <div className="set-reminder-foot">
      <Field label={t('language')} id="rem-lang">
        <select id="rem-lang" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
          <option value="">{t('lang_both')}</option>
          <option value="ar">{t('lang_ar')}</option>
          <option value="en">{t('lang_en')}</option>
        </select>
      </Field>
      <Button onClick={save}>{t('save')}</Button>
      </div>
      <p className="helper set-window"><Icon name="clock" size={16} />{t('send_window', { start: data.send_window.start, end: data.send_window.end })}</p>
    </Panel>
  )
}
