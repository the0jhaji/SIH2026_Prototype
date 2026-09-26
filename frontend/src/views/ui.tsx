import type { ReactNode } from 'react'
import { tint } from '../domain/safety'

/**
 * Card primitives.
 *
 * Every panel is a flex column with a fixed-height header and a
 * content-driven body, so a card is exactly as tall as the information it
 * holds. `fill` hands the leftover viewport height to the panel and
 * `scroll` lets a long list scroll inside it instead of growing the page.
 */
export function Panel({
  title,
  right,
  children,
  className = '',
  fill = false,
  scroll = false,
  accent,
}: {
  title: string
  right?: ReactNode
  children: ReactNode
  className?: string
  fill?: boolean
  scroll?: boolean
  /** Colour of a 2px inset rule under the header. */
  accent?: string
}) {
  return (
    <section
      className={`panel ${fill ? 'panel-fill' : ''} ${className}`}
      style={accent ? { borderTopColor: accent, borderTopWidth: 2 } : undefined}
    >
      <div className="panel-head">
        <h2 className="heading-title">{title}</h2>
        {right}
      </div>
      <div className={`panel-body ${scroll ? 'panel-body-fill' : ''}`}>{children}</div>
    </section>
  )
}

/** Uppercase monospace pill with an inline color accent. */
export function Badge({
  color,
  children,
  pulse = false,
  className = '',
}: {
  color: string
  children: ReactNode
  pulse?: boolean
  className?: string
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${className}`}
      style={{ borderColor: color, color, background: tint(color, 0.1) }}
    >
      {pulse && <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: color }} />}
      {children}
    </span>
  )
}

export function StatTile({
  label,
  value,
  color,
  title,
}: {
  label: string
  value: string
  color?: string
  title?: string
}) {
  return (
    <div className="tile px-2 py-1.5 text-center" title={title}>
      <p className="overline-label truncate">{label}</p>
      <p className="copy-value truncate" style={color ? { color } : undefined}>
        {value}
      </p>
    </div>
  )
}

export function KeyValue({
  label,
  value,
  color,
}: {
  label: string
  value: ReactNode
  color?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-outline-variant/20 py-1 last:border-0">
      <span className="shrink-0 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {label}
      </span>
      <span
        className="truncate text-right font-mono text-xs text-on-surface"
        style={color ? { color } : undefined}
      >
        {value}
      </span>
    </div>
  )
}

/**
 * Summary metric for a top-of-page status row. Shows the real value; the
 * caller decides what "no data" looks like rather than this inventing a 0.
 */
export function MetricCard({
  label,
  value,
  sub,
  color,
  active = false,
}: {
  label: string
  value: string
  sub?: string
  color?: string
  active?: boolean
}) {
  const tintColor = color ?? '#64748b'
  return (
    <div
      className="flex min-w-0 flex-col justify-center border bg-surface-container px-2.5 py-1.5"
      style={{
        borderColor: active ? tintColor : 'color-mix(in oklab, var(--t-outline-variant) 50%, transparent)',
        background: active ? tint(tintColor, 0.07) : undefined,
      }}
    >
      <p className="overline-label truncate">{label}</p>
      <p
        className="truncate font-mono text-xl font-bold leading-tight"
        style={{ color: color ?? 'var(--color-on-surface)' }}
      >
        {value}
      </p>
      {sub && <p className="truncate font-mono text-[10px] text-on-surface-variant">{sub}</p>}
    </div>
  )
}

/**
 * A single boolean condition rendered as label + state. Pairs with
 * {@link MetricCard} for status rows where one column must never invent a
 * number it does not have.
 */
export function StatusCard({
  label,
  value,
  color,
  sub,
}: {
  label: string
  value: string
  color?: string
  sub?: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 border border-outline-variant/40 bg-surface-container-low px-2.5 py-1.5">
      <span
        className="h-1.5 w-1.5 shrink-0"
        style={{ background: color ?? 'var(--t-outline)' }}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <p className="overline-label truncate">{label}</p>
        <p
          className="truncate font-mono text-xs font-bold uppercase tracking-wider"
          style={{ color: color ?? 'var(--color-on-surface)' }}
        >
          {value}
        </p>
        {sub && <p className="truncate font-mono text-[10px] text-on-surface-variant">{sub}</p>}
      </div>
    </div>
  )
}

/** Risk / mission-state pill driven by the shared colour maps. */
export function RiskBadge({
  color,
  children,
  pulse = false,
}: {
  color: string
  children: ReactNode
  pulse?: boolean
}) {
  return (
    <Badge color={color} pulse={pulse}>
      {children}
    </Badge>
  )
}

/**
 * The honest answer to "there is nothing here".
 *
 * Deliberately a small bordered block, not a stretched container: an empty
 * region that grows to fill a panel is the same visual defect as a blank
 * page. Callers that need to fill a tall region pair this with other real
 * information instead of padding the void.
 */
export function EmptyState({
  icon = 'inbox',
  title,
  description,
  status,
  lastUpdated,
  action,
  compact = false,
}: {
  icon?: string
  title: string
  description?: string
  status?: ReactNode
  lastUpdated?: string
  action?: ReactNode
  compact?: boolean
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-1.5 border border-dashed border-outline-variant/40 bg-surface-container-low/50 text-center ${
        compact ? 'px-3 py-3' : 'px-4 py-5'
      }`}
    >
      <span className="msym text-2xl leading-none text-on-surface-variant/50" aria-hidden="true">
        {icon}
      </span>
      <p className="font-mono text-[11px] font-bold uppercase tracking-[0.12em] text-on-surface">
        {title}
      </p>
      {description && (
        <p className="max-w-md font-mono text-[10px] leading-relaxed text-on-surface-variant">
          {description}
        </p>
      )}
      {(status || lastUpdated) && (
        <p className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant/70">
          {status}
          {status && lastUpdated ? ' · ' : ''}
          {lastUpdated}
        </p>
      )}
      {action}
    </div>
  )
}

/** One-line inline empty, for use inside an otherwise dense list. */
export function Empty({ label }: { label: string }) {
  return <p className="font-mono text-[11px] text-on-surface-variant">{label}</p>
}

/** Section rule with an optional trailing counter, used inside panels. */
export function SectionHeader({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="mb-1.5 flex items-center justify-between gap-2 border-b border-outline-variant/30 pb-1">
      <span className="overline-label truncate">{title}</span>
      {right}
    </div>
  )
}

/**
 * Lightweight nested block for grouping related readouts inside a panel.
 * Not a `.panel`: nesting full card chrome inside a card wastes the
 * vertical space this refactor is trying to reclaim.
 */
export function SubCard({
  title,
  right,
  children,
  className = '',
}: {
  title: string
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`flex min-w-0 flex-col border border-outline-variant/30 bg-surface-container-low/60 p-1.5 ${className}`}>
      <div className="mb-1 flex items-center justify-between gap-1.5">
        <span className="overline-label truncate">{title}</span>
        {right}
      </div>
      {children}
    </div>
  )
}
