import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Field, Message, Panel } from '../../components/ui'
import { patch } from '../../lib/api'

/** Profile preferences: language, numerals (display-only note in this phase), contact email and mobile. */
export default function ProfileTab() {
  const { t } = useTranslation('settings')
  const { me, setLanguage, refresh } = useAuth()
  const [email, setEmail] = useState('')
  const [mobile, setMobile] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  if (!me) return null
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await patch('/api/auth/me/preferences', { contact_email: email, contact_mobile: mobile })
      setMsg({ kind: 'success', text: t('profile_saved') })
      await refresh()
    } catch {
      setMsg({ kind: 'error', text: t('profile_failed') })
    } finally {
      setSaving(false)
    }
  }
  return (
    <div>
      {msg && <Message kind={msg.kind}>{msg.text}</Message>}
      <Panel title={t('tab_profile')} id="profile">
        <dl className="kv">
          <dt>{t('profile_identity')}</dt><dd><bdi>{me.display_name}</bdi></dd>
          <dt>{t('profile_level')}</dt><dd><bdi dir="ltr">{me.assurance_level}</bdi></dd>
        </dl>
        <form onSubmit={save}>
          <Field label={t('profile_language')} id="pref-lang">
            <select id="pref-lang" value={me.language} onChange={(e) => setLanguage(e.target.value as 'ar' | 'en')}>
              <option value="ar">العربية</option>
              <option value="en">English</option>
            </select>
          </Field>
          <Field label={t('profile_numerals')} id="pref-numerals" hint={t('profile_numerals_note')}>
            <input id="pref-numerals" value={me.numerals} readOnly aria-readonly="true" dir="ltr" />
          </Field>
          <Field label={t('profile_email')} id="pref-email"><input id="pref-email" type="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label={t('profile_mobile')} id="pref-mobile"><input id="pref-mobile" type="tel" dir="ltr" value={mobile} onChange={(e) => setMobile(e.target.value)} /></Field>
          <Button type="submit" disabled={saving}>{saving ? t('common.saving', { ns: 'translation' }) : t('common.save', { ns: 'translation' })}</Button>
        </form>
      </Panel>
    </div>
  )
}
