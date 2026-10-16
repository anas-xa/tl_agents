import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, Empty, Field, Message, PageHeader, Pagination, Skeleton, StatCard, Tabs, Toolbar, usePaged } from '../../components/ui'
import { Icon } from '../../components/Icon'
import { formatDate, formatNumber } from '../../lib/format'
import { get } from '../../lib/api'
import { humanize, preview, shortDate } from './lib'
import './i18n'
import './core.css'

interface ConfigRow { key: string; version: number; value: unknown; unit: string | null; owner: string; status: string; label: string | null; effective_from: string; description?: string | null; changed_by?: string | null; approved_by?: string | null; change_reason?: string | null }
interface RuleRow { rule_id: string; version: string; title: string; instrument: string | null; status: string; confirmed_by: string | null; effective_from: string | null; owner_role: string | null; effective_to?: string | null; source?: string | null; parameters?: unknown }

type Status = 'confirmed' | 'provisional' | 'to_be_confirmed'
const tone = (s: string) => (s === 'confirmed' ? 'ok' : s === 'provisional' ? 'attention' : 'urgent')
const OTHER = '__other'

function StatusChip({ status, title }: { status: string; title?: string | null }) {
  const { t } = useTranslation()
  return <Chip tone={tone(status)} title={title ?? undefined}>{t(`core:status.${status}`, { defaultValue: humanize(status) })}</Chip>
}

function matches(q: string, ...fields: unknown[]) {
  if (!q) return true
  return fields.some((f) => f !== null && f !== undefined && (typeof f === 'string' ? f : JSON.stringify(f)).toLowerCase().includes(q))
}

/** Configuration and rule-version registers (read view). Changes are made through the API with a reason and, where required, a second approver. */
export default function ConfigRegister() {
  const { t, i18n } = useTranslation()
  const lang = i18n.language.startsWith('ar') ? 'ar' : 'en'
  const [config, setConfig] = useState<ConfigRow[] | null>(null)
  const [rules, setRules] = useState<RuleRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<'config' | 'rules'>('config')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'' | Status>('')
  useEffect(() => {
    Promise.all([get<ConfigRow[]>('/api/admin/config'), get<RuleRow[]>('/api/admin/rules')]).then(([c, r]) => { setConfig(c); setRules(r) }).catch((e) => setErr(e.message))
  }, [])

  const rows: { status: string }[] = (tab === 'config' ? config : rules) ?? []
  const count = (s: Status) => rows.filter((r) => r.status === s).length
  const n = (v: number) => formatNumber(v, lang)
  const loaded = tab === 'config' ? config : rules

  return (
    <div className="core-page">
      <PageHeader eyebrow={t('nav.admin')} title={t('core:config_title')} subtitle={t('core:config_subtitle')} />
      {err && <Message kind="error">{err}</Message>}
      <Tabs
        label={t('core:registers')}
        idPrefix="reg"
        value={tab}
        onChange={(v) => setTab(v)}
        tabs={[
          { id: 'config', label: t('core:tab_config'), badge: config ? n(config.length) : undefined },
          { id: 'rules', label: t('core:tab_rules'), badge: rules ? n(rules.length) : undefined },
        ]}
      />
      <div role="tabpanel" id={`reg-${tab}-panel`} aria-labelledby={`reg-${tab}`}>
        {loaded && (
          <div className="stat-grid core-stats">
            <StatCard icon={tab === 'config' ? 'settings' : 'scale'} label={tab === 'config' ? t('core:stat_settings') : t('core:stat_rules')} value={n(rows.length)} />
            <StatCard icon="check" tone="ok" label={t('core:stat_confirmed')} value={n(count('confirmed'))} hint={t('core:of_total', { total: n(rows.length) })} />
            <StatCard icon="clock" tone="attention" label={t('core:stat_provisional')} value={n(count('provisional'))} hint={t('core:of_total', { total: n(rows.length) })} />
            <StatCard icon="alert" tone="urgent" label={t('core:stat_tbc')} value={n(count('to_be_confirmed'))} hint={t('core:of_total', { total: n(rows.length) })} />
          </div>
        )}
        <Toolbar label={t('common.filter')}>
          <div className="field core-search">
            <label htmlFor="reg-search">{tab === 'config' ? t('core:search_config') : t('core:search_rules')}</label>
            <div className="core-search-wrap">
              <Icon name="search" size={18} />
              <input id="reg-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
          <Field label={t('common.status')} id="reg-status">
            <select id="reg-status" value={status} onChange={(e) => setStatus(e.target.value as '' | Status)}>
              <option value="">{t('core:all_statuses')}</option>
              {(['confirmed', 'provisional', 'to_be_confirmed'] as Status[]).map((s) => <option key={s} value={s}>{t(`core:status.${s}`)}</option>)}
            </select>
          </Field>
        </Toolbar>
        {!loaded ? <Skeleton rows={6} /> : tab === 'config' ? (
          <ConfigGroups key={`${query.trim()}|${status}`} rows={config!} query={query.trim().toLowerCase()} status={status} lang={lang} />
        ) : (
          <RuleList rows={rules!} query={query.trim().toLowerCase()} status={status} lang={lang} />
        )}
      </div>
    </div>
  )
}

function NoMatch() {
  const { t } = useTranslation()
  return <Empty icon="search" title={t('core:no_match')} body={t('core:no_match_body')} />
}

function ConfigGroups({ rows, query, status, lang }: { rows: ConfigRow[]; query: string; status: string; lang: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const filtering = !!(query || status)
  const groups = useMemo(() => {
    const prefixOf = (k: string) => (k.includes('.') ? k.split('.')[0] : k)
    const sizes = new Map<string, number>()
    for (const r of rows) sizes.set(prefixOf(r.key), (sizes.get(prefixOf(r.key)) ?? 0) + 1)
    const map = new Map<string, ConfigRow[]>()
    for (const r of rows) {
      if (status && r.status !== status) continue
      if (!matches(query, r.key, r.value, r.owner, r.label, r.unit, r.description)) continue
      const p = prefixOf(r.key)
      const g = (sizes.get(p) ?? 0) > 1 ? p : OTHER
      if (!map.has(g)) map.set(g, [])
      map.get(g)!.push(r)
    }
    return [...map.entries()].sort(([a], [b]) => (a === OTHER ? 1 : b === OTHER ? -1 : a.localeCompare(b))).map(([id, items]) => ({ id, items }))
  }, [rows, query, status])
  const paged = usePaged(groups, 20)
  if (groups.length === 0) return <NoMatch />
  const isOpen = (id: string) => open[id] ?? filtering
  const setAll = (v: boolean) => setOpen(Object.fromEntries(groups.map((g) => [g.id, v])))
  return (
    <>
      <div className="section-title" style={{ marginTop: 0 }}>
        <h2 className="visually-hidden">{t('core:tab_config')}</h2>
        <span className="muted core-small">{t('core:group_settings', { count: groups.reduce((s, g) => s + g.items.length, 0) })}</span>
        <span className="actions" style={{ margin: 0 }}>
          <Button variant="secondary" className="btn-sm" onClick={() => setAll(true)}>{t('core:expand_all')}</Button>
          <Button variant="secondary" className="btn-sm" onClick={() => setAll(false)}>{t('core:collapse_all')}</Button>
        </span>
      </div>
      <div className="core-groups">
        {paged.pageItems.map((g) => {
          const confirmed = g.items.filter((r) => r.status === 'confirmed').length
          const tbc = g.items.filter((r) => r.status === 'to_be_confirmed').length
          return (
            <Group
              key={g.id}
              id={g.id}
              open={isOpen(g.id)}
              onToggle={() => setOpen((o) => ({ ...o, [g.id]: !isOpen(g.id) }))}
              title={g.id === OTHER ? t('core:other_group') : humanize(g.id)}
              code={g.id === OTHER ? null : `${g.id}.*`}
              stats={
                <>
                  <span>{t('core:group_confirmed', { n: formatNumber(confirmed, lang), total: formatNumber(g.items.length, lang) })}</span>
                  {tbc > 0 && <Chip tone="urgent">{t('core:group_tbc', { count: tbc })}</Chip>}
                </>
              }
            >
              <EntryList
                items={g.items}
                cols={[t('core:col_key'), t('core:col_value'), t('common.status'), t('core:col_owner'), t('core:col_version')]}
                render={(r) => ({
                  id: r.key,
                  cells: [
                    <span key="k" className="core-entry-key core-ellipsis core-mono" title={r.key}>{r.key}</span>,
                    <span key="v" className="core-entry-value core-ellipsis core-mono" dir="ltr" title={preview(r.value)}>{preview(r.value)}{r.unit ? ` ${r.unit}` : ''}</span>,
                    <span key="s" className="core-entry-status"><StatusChip status={r.status} title={r.label} /></span>,
                    <span key="o" className="core-entry-owner core-ellipsis" title={r.owner}>{r.owner}</span>,
                    <span key="ver" className="core-entry-version">v{r.version}</span>,
                  ],
                  body: (
                    <dl className="kv core-kv">
                      <dt>{t('core:f_value')}</dt><dd><pre className="code">{JSON.stringify(r.value, null, 2)}</pre></dd>
                      {r.unit && <><dt>{t('core:f_unit')}</dt><dd>{r.unit}</dd></>}
                      {r.label && <><dt>{t('core:f_note')}</dt><dd className="notice-tbc">{r.label}</dd></>}
                      {r.description && <><dt>{t('core:f_description')}</dt><dd>{r.description}</dd></>}
                      <dt>{t('core:col_owner')}</dt><dd>{r.owner}</dd>
                      <dt>{t('core:col_effective')}</dt><dd>{formatDate(r.effective_from, lang)}</dd>
                      <dt>{t('core:col_version')}</dt><dd>v{r.version}</dd>
                      {r.changed_by && <><dt>{t('core:f_changed_by')}</dt><dd><bdi>{r.changed_by}</bdi></dd></>}
                      {r.approved_by && <><dt>{t('core:f_approved_by')}</dt><dd><bdi>{r.approved_by}</bdi></dd></>}
                      {r.change_reason && <><dt>{t('core:f_reason')}</dt><dd>{r.change_reason}</dd></>}
                    </dl>
                  ),
                })}
              />
            </Group>
          )
        })}
      </div>
      <Pagination page={paged.page} pages={paged.pages} total={paged.total} pageSize={paged.pageSize} onPage={paged.setPage} />
    </>
  )
}

function Group({ id, title, code, stats, open, onToggle, children }: { id: string; title: string; code: string | null; stats: ReactNode; open: boolean; onToggle: () => void; children: ReactNode }) {
  const bodyId = `grp-${id}`
  return (
    <section className="core-group">
      <h3 style={{ margin: 0 }}>
        <button type="button" className="core-group-head" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
          <Icon name="chevron-end" size={18} className="core-chev" />
          <span className="core-group-name">
            <strong>{title}</strong>
            {code && <bdi dir="ltr" className="core-code">{code}</bdi>}
          </span>
          <span className="core-group-stats">{stats}</span>
        </button>
      </h3>
      {open && <div className="core-group-body" id={bodyId}>{children}</div>}
    </section>
  )
}

function EntryList<T>({ items, cols, render, className }: { items: T[]; cols: string[]; render: (r: T) => { id: string; cells: ReactNode[]; body: ReactNode }; className?: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<string | null>(null)
  const paged = usePaged(items, 25)
  return (
    <div className={className}>
      <div className="core-entry-cols" aria-hidden="true"><span />{cols.map((c) => <span key={c}>{c}</span>)}</div>
      <ul className="core-entries">
        {paged.pageItems.map((r) => {
          const e = render(r)
          const isOpen = open === e.id
          const bodyId = `entry-${e.id}`.replace(/[^a-zA-Z0-9_-]/g, '-')
          return (
            <li key={e.id} className="core-entry">
              <button type="button" className="core-entry-head" aria-expanded={isOpen} aria-controls={bodyId} onClick={() => setOpen(isOpen ? null : e.id)} title={t('core:show_entry')}>
                <Icon name="chevron-end" size={16} className="core-chev" />
                {e.cells}
              </button>
              {isOpen && <div className="core-entry-body" id={bodyId}>{e.body}</div>}
            </li>
          )
        })}
      </ul>
      {paged.pages > 1 && <div className="core-group-foot"><Pagination page={paged.page} pages={paged.pages} total={paged.total} pageSize={paged.pageSize} onPage={(p) => { setOpen(null); paged.setPage(p) }} /></div>}
    </div>
  )
}

function RuleList({ rows, query, status, lang }: { rows: RuleRow[]; query: string; status: string; lang: string }) {
  const { t } = useTranslation()
  const items = useMemo(() => rows.filter((r) => (!status || r.status === status) && matches(query, r.rule_id, r.title, r.owner_role, r.instrument, r.confirmed_by)), [rows, query, status])
  if (items.length === 0) return <NoMatch />
  return (
    <section className="core-group core-rules" aria-label={t('core:tab_rules')}>
      <EntryList
        key={`${query}|${status}`}
        items={items}
        cols={[t('core:col_rule'), t('core:col_title'), t('common.status'), t('core:col_effective'), t('core:col_owner')]}
        render={(r) => ({
          id: `${r.rule_id}@${r.version}`,
          cells: [
            <span key="k" className="core-entry-key core-ellipsis core-mono" title={`${r.rule_id} ${r.version}`}>{r.rule_id}</span>,
            <span key="v" className="core-entry-value core-ellipsis" title={r.title}>{r.title}</span>,
            <span key="s" className="core-entry-status"><StatusChip status={r.status} /></span>,
            <span key="d" className="core-entry-date core-ellipsis nowrap">{r.effective_from ? shortDate(r.effective_from, lang) : '—'}</span>,
            <span key="o" className="core-entry-owner core-ellipsis" title={r.owner_role ?? ''}>{r.owner_role ?? '—'}</span>,
          ],
          body: (
            <dl className="kv core-kv">
              <dt>{t('core:col_title')}</dt><dd>{r.title}</dd>
              <dt>{t('core:col_version')}</dt><dd><bdi dir="ltr" className="core-mono">{r.version}</bdi></dd>
              {r.instrument && <><dt>{t('core:f_instrument')}</dt><dd>{r.instrument}</dd></>}
              <dt>{t('core:col_effective')}</dt><dd>{r.effective_from ? formatDate(r.effective_from, lang) : '—'}</dd>
              {r.effective_to && <><dt>{t('core:f_effective_to')}</dt><dd>{formatDate(r.effective_to, lang)}</dd></>}
              <dt>{t('core:f_confirmed_by')}</dt><dd>{r.confirmed_by ?? '—'}</dd>
              {r.source && <><dt>{t('core:f_source')}</dt><dd>{r.source}</dd></>}
              <dt>{t('core:col_owner')}</dt><dd>{r.owner_role ?? '—'}</dd>
              {r.parameters !== undefined && r.parameters !== null && <><dt>{t('core:f_parameters')}</dt><dd><pre className="code">{JSON.stringify(r.parameters, null, 2)}</pre></dd></>}
            </dl>
          ),
        })}
      />
    </section>
  )
}
