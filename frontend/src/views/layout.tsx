import type { ReactNode } from 'react'
import { formatTimestamp } from '../lib/time'
import { type TimelineEntry } from './helpers'

/**
 * Layout primitives shared by every view.
 *
 * Components only — anything that is not a component lives in
 * `./helpers` so fast refresh keeps working on a module that exports
 * components.
 */

/**
 * The scrolling body of one view.
 *
 * `height: 100%` plus a column flex means a `page-fill` row can claim the
 * remaining viewport instead of the page ending in a dead strip. Only the
 * fixed rows above/below it can push this container into a scroll, so a
 * dense page never scrolls twice.
 */
export function PageShell({ children }: { children: ReactNode }) {
  return <div className="page-scroll">{children}</div>
}

/** 12-column responsive grid. Cells declare a span, never a pixel width. */
export function Grid({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`dash-grid ${className}`}>{children}</div>
}

export function Cell({ span = 12, children }: { span?: number; children: ReactNode }) {
  return <div className={`dash-cell span-${span}`}>{children}</div>
}

/** A row of equal-width metric cards that wraps onto 12 / 6 / 3 / 2 columns. */
export function SummaryRow({ children }: { children: ReactNode }) {
  return (
    <Grid>
      <Cell span={12}>
        <div className="grid gap-[var(--grid-gap)] sm:grid-cols-2 lg:grid-cols-4">
          {children}
        </div>
      </Cell>
    </Grid>
  )
}

// ── timeline ───────────────────────────────────────────────────────────

/**
 * Vertical event log. A timeline is one of the few things allowed to be
 * tall, because it is real history rather than padding — but the entries
 * themselves are content-driven, never stretched.
 */
export function Timeline({
  entries,
  empty,
  className = '',
}: {
  entries: TimelineEntry[]
  empty?: ReactNode
  className?: string
}) {
  if (entries.length === 0) return <>{empty ?? null}</>
  return (
    <ol className={`rows ${className}`}>
      {entries.map((e, i) => (
        <li
          key={e.id}
          className="grid grid-cols-[4.5rem_0.5rem_minmax(0,1fr)] items-start gap-x-1.5"
        >
          <time
            className="pt-px text-right font-mono text-[10px] tabular-nums text-on-surface-variant"
            dateTime={new Date(e.ts).toISOString()}
          >
            {formatTimestamp(e.ts)}
          </time>
          <span className="relative flex h-full justify-center">
            {i < entries.length - 1 && (
              <span
                className="absolute top-2.5 bottom-0 w-px bg-outline-variant/30"
                aria-hidden="true"
              />
            )}
            <span
              className="relative mt-1 h-1.5 w-1.5 shrink-0"
              style={{ background: e.color }}
              aria-hidden="true"
            />
          </span>
          <div className="min-w-0 pb-1">
            <p className="truncate font-mono text-[11px] font-bold uppercase tracking-wider">
              {e.title}
            </p>
            {e.detail && (
              <p className="font-mono text-[10px] leading-snug text-on-surface">{e.detail}</p>
            )}
            {e.meta && (
              <p className="truncate font-mono text-[10px] text-on-surface-variant">{e.meta}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

// ── filters ────────────────────────────────────────────────────────────

/** Segmented filter row. Purely a view over data already loaded. */
export function FilterBar({
  options,
  value,
  onChange,
  search,
  onSearch,
  placeholder = 'Search…',
  right,
}: {
  options: readonly { value: string; label: string; count?: number }[]
  value: string
  onChange: (value: string) => void
  search?: string
  onSearch?: (value: string) => void
  placeholder?: string
  right?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {options.map(o => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={`border px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-wider transition ${
              active
                ? 'border-primary bg-primary/15 text-primary'
                : 'border-outline-variant/50 bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'
            }`}
          >
            {o.label}
            {o.count != null && <span className="ml-1 opacity-70">{o.count}</span>}
          </button>
        )
      })}
      {onSearch && (
        <label className="ml-auto flex min-w-[10rem] flex-1 items-center gap-1.5 border border-outline-variant/50 bg-surface-container-low px-2 py-1 sm:flex-none">
          <span className="msym text-sm leading-none text-on-surface-variant" aria-hidden="true">
            search
          </span>
          <input
            type="search"
            value={search ?? ''}
            onChange={e => onSearch(e.target.value)}
            placeholder={placeholder}
            className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none"
          />
        </label>
      )}
      {right}
    </div>
  )
}

// ── table ──────────────────────────────────────────────────────────────

export interface DataTableColumn<T> {
  header: string
  render: (row: T) => ReactNode
  className?: string
}

/**
 * Dense, selectable record table. Rows are buttons so keyboard users can
 * drive the detail pane that most log-style views pair with it.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  selectedKey,
  onSelect,
  empty,
}: {
  columns: readonly DataTableColumn<T>[]
  rows: readonly T[]
  rowKey: (row: T) => string
  selectedKey?: string | null
  onSelect?: (row: T) => void
  empty?: ReactNode
}) {
  if (rows.length === 0) return <>{empty ?? null}</>
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-outline-variant/40">
            {columns.map(c => (
              <th
                key={c.header}
                scope="col"
                className={`overline-label whitespace-nowrap px-2 py-1 font-semibold ${c.className ?? ''}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const key = rowKey(row)
            const selected = key === selectedKey
            return (
              <tr
                key={key}
                onClick={onSelect ? () => onSelect(row) : undefined}
                onKeyDown={
                  onSelect
                    ? e => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          onSelect(row)
                        }
                      }
                    : undefined
                }
                tabIndex={onSelect ? 0 : undefined}
                role={onSelect ? 'button' : undefined}
                aria-selected={onSelect ? selected : undefined}
                className={`border-b border-outline-variant/20 align-top ${
                  onSelect ? 'cursor-pointer' : ''
                } ${selected ? 'bg-primary/10' : 'hover:bg-surface-container-high/60'}`}
              >
                {columns.map(c => (
                  <td
                    key={c.header}
                    className={`px-2 py-1.5 font-mono text-[11px] text-on-surface ${c.className ?? ''}`}
                  >
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
