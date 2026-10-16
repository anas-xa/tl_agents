import { useTranslation } from 'react-i18next'
import { Icon } from '../../components/Icon'
import { PHASE_A, PHASE_B, type Toggle, type ToggleMeta } from './types'

/**
 * Function toggles (SC11): real switches with a text label and an On/Off state. Phase A toggles are off by
 * default; Phase B toggles are built but locked behind the versioned per-right switch and show the locked wording.
 */
export function RightsToggles({ value, onChange, meta, readOnly = false }: { value: Toggle[]; onChange?: (next: Toggle[]) => void; meta: ToggleMeta[]; readOnly?: boolean }) {
  const { t } = useTranslation('settings')
  const lockedFor = (x: Toggle) => meta.find((m) => m.toggle === x)?.locked ?? true
  return (
    <div className="set-rights-list">
      {PHASE_A.map((x) => <Row key={x} toggle={x} locked={false} value={value} onChange={onChange} readOnly={readOnly} />)}
      <h3 className="set-rights-sub">{t('phase_b_section')}</h3>
      <p className="helper">{t('only_you_approve')}</p>
      {PHASE_B.map((x) => <Row key={x} toggle={x} locked={lockedFor(x)} value={value} onChange={onChange} readOnly={readOnly} />)}
    </div>
  )
}

function Row({ toggle, locked, value, onChange, readOnly }: { toggle: Toggle; locked: boolean; value: Toggle[]; onChange?: (next: Toggle[]) => void; readOnly: boolean }) {
  const { t } = useTranslation('settings')
  const on = value.includes(toggle)
  const disabled = readOnly || locked
  return (
      <div className={`switch set-switch ${on ? 'is-on' : ''}`}>
        <input
          className="set-toggle"
          type="checkbox"
          role="switch"
          id={`toggle-${toggle}`}
          checked={on}
          disabled={disabled}
          aria-checked={on}
          aria-describedby={`toggle-${toggle}-desc`}
          onChange={(e) => onChange?.(e.target.checked ? [...value, toggle] : value.filter((v) => v !== toggle))}
        />
        <div>
          <label htmlFor={`toggle-${toggle}`} className="set-switch-label">{t(`fn_${toggle}`)}</label>
          <div className="desc" id={`toggle-${toggle}-desc`}>
            {t(`fn_${toggle}_desc`)}
            {locked && (
              <div className="set-locked">
                <Icon name="lock" size={14} /><strong>{t('locked')}</strong> <span className="notice-tbc">{t('requires_evidence')} · {t('proposed')}</span>
              </div>
            )}
          </div>
        </div>
        <span className="switch-state" aria-hidden="true">{on ? t('on') : t('off')}</span>
      </div>
  )
}

export function RightsSummary({ value, name, company }: { value: Toggle[]; name?: string | null; company?: string }) {
  const { t } = useTranslation('settings')
  return (
    <ul className="set-summary">
      <li>{t('can_view', { v: value.includes('view_dashboard') ? t('yes') : t('no') })}</li>
      <li>{t('can_prepare', { v: value.includes('prepare_data') ? t('yes') : t('no') })}</li>
      <li>{t('can_consent')}</li>
      <li>{t('can_approve')}</li>
      <li>{t('can_subscription')}</li>
      {name && company && <li className="helper">{t('only_you_approve')}</li>}
    </ul>
  )
}
