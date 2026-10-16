import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon, type IconName } from './Icon'

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
  const icons: Record<string, IconName> = { info: 'info', error: 'alert', warning: 'alert', success: 'check' }
  return (
    <div className={`message message-${kind}`} role={kind === 'error' ? 'alert' : 'status'} id={id} tabIndex={-1}>
      <span aria-hidden="true" className="message-icon"><Icon name={icons[kind]} size={18} /></span>
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

export function Empty({ icon = '○', title, body, action }: { icon?: IconName | string; title: ReactNode; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon" aria-hidden="true">{icon.length > 2 ? <Icon name={icon} size={28} /> : icon}</div>
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

/**
 * Page header: the same pattern on every screen. Eyebrow (section or company), title, one-line subtitle,
 * primary actions on the end side, and an optional meta row (status chips, data-as-of, honesty labels).
 */
export function PageHeader({ title, eyebrow, subtitle, actions, meta, id }: { title: ReactNode; eyebrow?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; meta?: ReactNode; id?: string }) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        {eyebrow && <p className="page-eyebrow">{eyebrow}</p>}
        <h1 id={id}>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
        {meta && <div className="page-meta">{meta}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}

/** Key figure: the number is the most prominent element; label above, context and status below. */
export function StatCard({ label, value, hint, status, icon, tone, footer, className }: { label: ReactNode; value: ReactNode; hint?: ReactNode; status?: ReactNode; icon?: IconName; tone?: 'ok' | 'attention' | 'urgent' | 'critical' | 'info' | 'draft'; footer?: ReactNode; className?: string }) {
  return (
    <div className={`stat-card ${tone ? `stat-card-${tone}` : ''} ${className ?? ''}`}>
      <div className="stat-card-label">
        {icon && <span className="stat-card-icon" aria-hidden="true"><Icon name={icon} size={18} /></span>}
        <span>{label}</span>
      </div>
      <div className="stat-card-value">{value}</div>
      {hint && <div className="stat-card-hint">{hint}</div>}
      {status && <div className="stat-card-status">{status}</div>}
      {footer && <div className="stat-card-footer">{footer}</div>}
    </div>
  )
}

/** Filters row above a list or table: wraps on small screens, controls share one height. */
export function Toolbar({ children, label }: { children: ReactNode; label?: string }) {
  return <div className="toolbar" role="group" aria-label={label}>{children}</div>
}

/** Shows the first `max` chips and folds the rest behind a "+n more" toggle (honesty labels stay reachable). */
export function ChipGroup({ children, max = 2 }: { children: ReactNode[]; max?: number }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const items = children.filter(Boolean)
  const shown = open ? items : items.slice(0, max)
  return (
    <span className="chip-group">
      {shown}
      {items.length > max && (
        <button type="button" className="chip chip-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? t('common.show_less') : t('common.more_n', { n: items.length - max })}
        </button>
      )}
    </span>
  )
}

/** Disclosure for secondary detail (rule versions, definitions, timestamps). */
export function Disclosure({ summary, children, open, className }: { summary: ReactNode; children: ReactNode; open?: boolean; className?: string }) {
  return (
    <details className={`disclosure ${className ?? ''}`} open={open}>
      <summary><Icon name="chevron-end" size={16} className="disclosure-chevron" /><span>{summary}</span></summary>
      <div className="disclosure-body">{children}</div>
    </details>
  )
}

/** Single-row tabs (scroll horizontally, never wrap) with arrow-key navigation (WAI-ARIA tabs pattern). */
export function Tabs<T extends string>({ tabs, value, onChange, label, idPrefix = 'tab' }: { tabs: { id: T; label: ReactNode; badge?: ReactNode }[]; value: T; onChange: (id: T) => void; label: string; idPrefix?: string }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const move = (delta: number) => {
    const i = tabs.findIndex((t) => t.id === value)
    const next = tabs[(i + delta + tabs.length) % tabs.length]
    onChange(next.id)
    refs.current[next.id]?.focus()
  }
  return (
    <div className="tabs" role="tablist" aria-label={label}
      onKeyDown={(e) => {
        const rtl = document.documentElement.dir === 'rtl'
        if (e.key === 'ArrowRight') { e.preventDefault(); move(rtl ? -1 : 1) }
        if (e.key === 'ArrowLeft') { e.preventDefault(); move(rtl ? 1 : -1) }
      }}>
      {tabs.map((t) => (
        <button key={t.id} ref={(el) => { refs.current[t.id] = el }} type="button" role="tab" id={`${idPrefix}-${t.id}`} aria-selected={t.id === value} aria-controls={`${idPrefix}-${t.id}-panel`} tabIndex={t.id === value ? 0 : -1} onClick={() => onChange(t.id)}>
          {t.label}{t.badge !== undefined && <span className="tab-badge">{t.badge}</span>}
        </button>
      ))}
    </div>
  )
}

/** Client-side paging for long lists: returns the current page slice; resets to page 1 when the list changes length. */
export function usePaged<T>(items: T[], pageSize = 25) {
  const [requested, setPage] = useState(1)
  const pages = Math.max(1, Math.ceil(items.length / pageSize))
  const page = Math.min(requested, pages) // a shorter list (new filter) never leaves an empty page
  const pageItems = useMemo(() => items.slice((page - 1) * pageSize, page * pageSize), [items, page, pageSize])
  return { page, pages, setPage, pageItems, total: items.length, pageSize }
}

export function Pagination({ page, pages, total, pageSize, onPage }: { page: number; pages: number; total: number; pageSize: number; onPage: (p: number) => void }) {
  const { t } = useTranslation()
  if (total <= pageSize) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  const nums = Array.from({ length: pages }, (_, i) => i + 1).filter((n) => n === 1 || n === pages || Math.abs(n - page) <= 1)
  return (
    <nav className="pagination" aria-label={t('common.pagination')}>
      <span className="pagination-count" aria-live="polite">{t('common.showing', { from, to, total })}</span>
      <span className="pagination-pages">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label={t('common.previous')}>
          <Icon name="chevron-start" size={16} className="flip-rtl" />
        </button>
        {nums.map((n, i) => (
          <span key={n} className="pagination-num">
            {i > 0 && n - nums[i - 1] > 1 && <span className="muted" aria-hidden="true">…</span>}
            <button type="button" className={`btn btn-sm ${n === page ? 'btn-primary' : 'btn-secondary'}`} aria-current={n === page ? 'page' : undefined} aria-label={t('common.page_n', { n })} onClick={() => onPage(n)}>{n}</button>
          </span>
        ))}
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => onPage(page + 1)} disabled={page >= pages} aria-label={t('common.next')}>
          <Icon name="chevron-end" size={16} className="flip-rtl" />
        </button>
      </span>
    </nav>
  )
}
