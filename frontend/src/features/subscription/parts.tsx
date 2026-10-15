import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Dialog, Ident, Message, Skeleton } from '../../components/ui'
import { formatAED, formatDate, formatNumber } from '../../lib/format'
import { BADGE_ICON, BADGE_TONE, useFetch, type Param, type Sub } from './lib'

/** Proposed-wording label shown beside every commercial or legal sentence. */
export function Proposed() {
  const { t } = useTranslation('subscription')
  return <span className="notice-tbc"> ({t('proposed')})</span>
}

export function StatusBadge({ badge }: { badge: string }) {
  const { t } = useTranslation('subscription')
  return <Chip tone={BADGE_TONE[badge] ?? 'neutral'} icon={BADGE_ICON[badge] ?? '○'}>{t(`screen.badge_${badge}`)}</Chip>
}

/** Lifecycle message per badge (Q276); amounts never appear in these messages. */
export function StatusMessage({ sub }: { sub: Sub }) {
  const { t, i18n } = useTranslation('subscription')
  const lang = i18n.language
  const params: Record<string, string> = { start: formatDate(sub.start_date, lang), end: formatDate(sub.end_date, lang), date: formatDate(sub.ended_on, lang) }
  if (sub.badge === 'ended') {
    const known = ['licence_not_renewed', 'licence_cancelled', 'licence_suspended', 'licence_transferred']
    params.cause = t(`screen.cause_${known.includes(sub.ended_cause ?? '') ? sub.ended_cause : 'other'}`)
  }
  const kind = sub.badge === 'held_for_review' ? 'warning' : 'info'
  return <Message kind={kind}>{t(`screen.msg_${sub.badge}`, params)}</Message>
}

/**
 * Fee line card: licence fee and subscription are always separate rows; net / VAT / gross shown separately and
 * labelled indicative; amounts are examples until the fee schedule is confirmed. Hidden when the backend sends
 * no fee (held for review, cancelled, opted out).
 */
export function FeeCard({ sub }: { sub: Sub }) {
  const { t, i18n } = useTranslation('subscription')
  const lang = i18n.language
  const fee = sub.fee
  if (!fee) return null
  const ex = fee.label === 'example'
  const exampleTag = ex ? <Chip tone="draft" icon="✎">{t('example')}</Chip> : null
  return (
    <section className="card" aria-labelledby={`fee-${sub.id}`}>
      <h3 id={`fee-${sub.id}`}>{t('screen.fee_card')} {exampleTag}</h3>
      {ex && <Message kind="info">{t('screen.example_banner')}</Message>}
      <dl className="kv">
        <dt>{t('screen.licence_fee_row')}</dt>
        <dd>{t('screen.licence_fee_value')}</dd>
        <dt>{t('screen.subscription_row')}</dt>
        <dd>
          <bdi dir="ltr">{formatAED(fee.gross_fils, lang)}</bdi> {t('screen.per_year')} {exampleTag}
          <div className="hint">{t('screen.monthly_caption', { amount: formatNumber(fee.monthly_display_fils / 100, lang), version: sub.fee_schedule_version })}</div>
        </dd>
        <dt>{t('screen.net')}</dt>
        <dd><bdi dir="ltr">{formatAED(fee.net_fils, lang)}</bdi></dd>
        <dt>{t('screen.vat')}</dt>
        <dd><bdi dir="ltr">{formatAED(fee.vat_fils, lang)}</bdi> <span className="notice-tbc">{t('screen.vat_tbc')}</span></dd>
        <dt>{t('screen.gross')}</dt>
        <dd><bdi dir="ltr">{formatAED(fee.gross_fils, lang)}</bdi></dd>
      </dl>
      <p>{t('screen.collected_by_det')}</p>
      <p>{t('screen.separate_line')}<Proposed /></p>
      <p>{t('screen.not_dependent')}<Proposed /></p>
      <p className="hint">
        {t('screen.fee_schedule_short', { version: sub.fee_schedule_version })} · {sub.opt_out_refund_config_version ? t('screen.opt_out_settings', { version: sub.opt_out_refund_config_version }) : t('screen.opt_out_settings_not_set')}
      </p>
    </section>
  )
}

/** Every parameter still to be confirmed with DET is shown as such, never as a number. */
export function ParametersList({ parameters }: { parameters: Record<string, Param> }) {
  const { t } = useTranslation('subscription')
  const keys = ['opt_out_window_days', 'refund_window_days', 'cancel_effective', 'refund_mode', 'notice_period']
  return (
    <section className="card" aria-labelledby="sub-params">
      <h3 id="sub-params">{t('screen.parameters')}</h3>
      <Message kind="info">{t('screen.det_rule_not_set')}</Message>
      <dl className="kv">
        {keys.map((k) => {
          const p = parameters[k]
          return (
            <div key={k} style={{ display: 'contents' }}>
              <dt>{t(`screen.param_${k}`)}</dt>
              <dd>{p && p.confirmed && p.value !== null ? String(p.value) : <Chip tone="attention" icon="◷">{t('tbc')}</Chip>}</dd>
            </div>
          )
        })}
      </dl>
      <p>{t('screen.refund_placeholder')}<Proposed /></p>
    </section>
  )
}

interface Terms { version: string; label: string; sections: { key: string; en: string; ar: string }[] }

/** Terms side sheet: traps focus via the shared Dialog, Esc closes, focus returns to the opener. */
export function TermsSheet({ companyId, open, onClose }: { companyId: string; open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation('subscription')
  const { data, error, loading, reload } = useFetch<Terms>(open ? `/api/companies/${companyId}/subscription/terms` : null, [open])
  const closeBtn = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (open) closeBtn.current?.focus()
  }, [open])
  return (
    <Dialog open={open} title={t('screen.terms_title')} onClose={onClose} labelledBy="terms-title">
      {loading && !data && <Skeleton rows={4} />}
      {error && !data && <Message kind="error">{t('screen.error')} <Button variant="link" onClick={reload}>{t('screen.try_again')}</Button></Message>}
      {data && (
        <>
          <p><Chip tone="draft" icon="✎">{t('proposed')}</Chip> <Ident>{data.version}</Ident></p>
          {data.sections.map((s) => <p key={s.key}>{i18n.language.startsWith('ar') ? s.ar : s.en}</p>)}
        </>
      )}
      <div className="actions"><Button ref={closeBtn} variant="secondary" onClick={onClose}>{t('translation:common.close')}</Button></div>
    </Dialog>
  )
}
