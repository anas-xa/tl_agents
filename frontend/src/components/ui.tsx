import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/** Status chip: always icon + text, never colour alone. */
export function Chip({ tone = 'neutral', icon, children, title }: { tone?: 'neutral' | 'ok' | 'attention' | 'urgent' | 'critical' | 'info' | 'draft'; icon?: string; children: ReactNode; title?: string }) {
  const icons: Record<string, string> = { neutral: '○', ok: '✓', attention: '◔', urgent: '!', critical: '✕', info: 'i', draft: '✎' }
  return (
    <span className={`chip chip-${tone}`} title={title}>
      <span aria-hidden="true" className="chip-icon">{icon ?? icons[tone]}</span>
      <span>{children}</span>
    </span>
  )
}

export function Panel({ title, children, actions, tone, id, className }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; tone?: 'info' | 'warning' | 'error' | 'success'; id?: string; className?: string }) {
  return (
    <section className={`panel ${tone ? `panel-${tone}` : ''} ${className ?? ''}`} id={id} aria-labelledby={id ? `${id}-title` : undefined}>
      {(title || actions) && (
        <header className="panel-header">
          {title && <h2 id={id ? `${id}-title` : undefined}>{title}</h2>}
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  )
}

export function Message({ kind, children, id }: { kind: 'info' | 'error' | 'warning' | 'success'; children: ReactNode; id?: string }) {
  const icons = { info: 'i', error: '✕', warning: '!', success: '✓' }
  return (
    <div className={`message message-${kind}`} role={kind === 'error' ? 'alert' : 'status'} id={id} tabIndex={-1}>
      <span aria-hidden="true" className="message-icon">{icons[kind]}</span>
      <div>{children}</div>
    </div>
  )
}

export function Button({ variant = 'primary', ref, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'link'; ref?: React.Ref<HTMLButtonElement> }) {
  return <button ref={ref} {...props} className={`btn btn-${variant} ${props.className ?? ''}`} />
}

export function Field({ label, children, hint, required, id }: { label: ReactNode; children: ReactNode; hint?: ReactNode; required?: boolean; id?: string }) {
  const { t } = useTranslation()
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {required && <span className="required"> ({t('common.required')})</span>}
      </label>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

/** Label for AI-prepared content: always shown with its status. */
export function AiLabel({ status }: { status?: string }) {
  const { t } = useTranslation()
  return <Chip tone="draft" icon="✎">{t('shell.ai_prepared_draft')}{status ? ` · ${status}` : ''}</Chip>
}

/** Identifier (TRN, licence number, reference): Western digits, bidi-isolated. */
export function Ident({ children }: { children: ReactNode }) {
  return <bdi className="ident" dir="ltr">{children}</bdi>
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-row" />
      ))}
    </div>
  )
}

export function Empty({ icon = '○', title, body, action }: { icon?: string; title: ReactNode; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <h3>{title}</h3>
      {body && <p>{body}</p>}
      {action}
    </div>
  )
}

export function Table({ headers, children, caption }: { headers: ReactNode[]; children: ReactNode; caption?: ReactNode }) {
  return (
    <div className="table-wrap">
      <table>
        {caption && <caption>{caption}</caption>}
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i} scope="col">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

export function Dialog({ open, title, children, onClose, labelledBy = 'dialog-title' }: { open: boolean; title: ReactNode; children: ReactNode; onClose: () => void; labelledBy?: string }) {
  if (!open) return null
  return (
    <div className="dialog-backdrop" onKeyDown={(e) => e.key === 'Escape' && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        <h2 id={labelledBy}>{title}</h2>
        {children}
      </div>
    </div>
  )
}
