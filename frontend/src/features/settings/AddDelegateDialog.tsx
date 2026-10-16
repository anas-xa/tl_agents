import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../app/auth'
import { Button, Dialog, Field, Message } from '../../components/ui'
import { ApiError, post } from '../../lib/api'
import { RightsSummary, RightsToggles } from './RightsToggles'
import type { Toggle, ToggleMeta } from './types'

/** Invite stepper (SC11): who, which company, which functions (all off), review and confirm. */
export default function AddDelegateDialog({ open, companyId, meta, onClose, onDone }: { open: boolean; companyId: string; meta: ToggleMeta[]; onClose: () => void; onDone: (msg: string) => void }) {
  const { t, i18n } = useTranslation('settings')
  const { me, can } = useAuth()
  const [step, setStep] = useState(1)
  const [form, setForm] = useState({ emirates_id: '', entered_name: '', email: '', mobile: '', company_id: companyId })
  const [toggles, setToggles] = useState<Toggle[]>([])
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [step])
  if (!open || !me) return null
  const companies = me.companies.filter((c) => can('delegates.manage', c.company_id))
  const company = companies.find((c) => c.company_id === form.company_id)
  const companyName = company ? (i18n.language === 'ar' ? company.trade_name_ar : company.trade_name_en) : ''
  const submit = async () => {
    setSaving(true)
    setErr(null)
    try {
      await post(`/api/companies/${form.company_id}/delegates`, { emirates_id: form.emirates_id, entered_name: form.entered_name || null, email: form.email || null, mobile: form.mobile || null, toggles })
      onDone(t('invited_ok'))
      onClose()
    } catch (e) {
      const code = e instanceof ApiError ? e.code : ''
      setErr(code === 'LEVEL_TOO_LOW_FOR_ACTION' ? t('reauth_failed') : code === 'NO_PERMISSION' || code === 'OWNER_ONLY' ? t('owner_only') : code === 'RIGHT_SWITCHED_OFF' ? t('locked') : code === 'COMPANY_ON_HOLD' ? t('on_hold') : code === 'DET_DATA_STALE' ? t('stale') : code === 'EMIRATES_ID_INVALID' || code === 'DELEGATE_LIMIT_COMPANY' || code === 'DELEGATE_LIMIT_PERSON' || code === 'ALREADY_DELEGATE' || code === 'ALREADY_OWNER' || code === 'INVITATION_PENDING' || code === 'ROLE_COMBINATION_REFUSED' ? (e as Error).message : t('invite_failed'))
    } finally {
      setSaving(false)
    }
  }
  const stepTitles = [t('step_who'), t('step_company'), t('step_functions'), t('step_review')]
  return (
    <Dialog open={open} title={t('invite_title')} onClose={onClose} labelledBy="invite-title">
      <div className="set-steps" aria-hidden="true">
        {stepTitles.map((x, i) => <span key={x} className={i + 1 < step ? 'is-done' : i + 1 === step ? 'is-current' : ''} />)}
      </div>
      <div className="stepper">{t('step', { n: step })}</div>
      <h3 ref={heading} tabIndex={-1} className="set-step-title">{stepTitles[step - 1]}</h3>
      {err && <Message kind="error">{err}</Message>}
      {step === 1 && (
        <form onSubmit={(e) => { e.preventDefault(); setStep(2) }}>
          <Field label={t('emirates_id')} id="inv-eid" required hint={t('emirates_id_hint')}>
            <input id="inv-eid" required inputMode="numeric" dir="ltr" value={form.emirates_id} onChange={(e) => setForm({ ...form, emirates_id: e.target.value })} placeholder="784-XXXX-XXXXXXX-X" />
          </Field>
          <Field label={t('entered_name')} id="inv-name" hint={t('entered_name_hint')}>
            <input id="inv-name" value={form.entered_name} onChange={(e) => setForm({ ...form, entered_name: e.target.value })} />
          </Field>
          <Field label={t('email')} id="inv-email"><input id="inv-email" type="email" dir="ltr" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label={t('mobile')} id="inv-mobile"><input id="inv-mobile" type="tel" dir="ltr" value={form.mobile} onChange={(e) => setForm({ ...form, mobile: e.target.value })} /></Field>
          <div className="dialog-actions"><Button type="button" variant="secondary" onClick={onClose}>{t('common.cancel', { ns: 'translation' })}</Button><Button type="submit">{t('common.next', { ns: 'translation' })}</Button></div>
        </form>
      )}
      {step === 2 && (
        <div>
          <Field label={t('company_label')} id="inv-company">
            <select id="inv-company" value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })}>
              {companies.map((c) => <option key={c.company_id} value={c.company_id}>{i18n.language === 'ar' ? c.trade_name_ar : c.trade_name_en}</option>)}
            </select>
          </Field>
          <div className="dialog-actions"><Button variant="secondary" onClick={() => setStep(1)}>{t('common.back', { ns: 'translation' })}</Button><Button onClick={() => setStep(3)}>{t('common.next', { ns: 'translation' })}</Button></div>
        </div>
      )}
      {step === 3 && (
        <div>
          <RightsToggles value={toggles} onChange={setToggles} meta={meta} />
          <div className="dialog-actions"><Button variant="secondary" onClick={() => setStep(2)}>{t('common.back', { ns: 'translation' })}</Button><Button onClick={() => setStep(4)}>{t('common.next', { ns: 'translation' })}</Button></div>
        </div>
      )}
      {step === 4 && (
        <div>
          <p className="set-review-who"><strong><bdi>{form.entered_name || '—'}</bdi></strong> · <bdi>{companyName}</bdi></p>
          <RightsSummary value={toggles} name={form.entered_name} company={companyName} />
          <p className="helper">{t('statement')}</p>
          <div className="dialog-actions" aria-live="polite">
            <Button variant="secondary" onClick={() => setStep(3)} disabled={saving}>{t('common.back', { ns: 'translation' })}</Button>
            <Button onClick={submit} disabled={saving}>{saving ? t('common.saving', { ns: 'translation' }) : t('confirm_invite')}</Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}
