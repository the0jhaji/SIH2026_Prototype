import type { ReactNode } from 'react'
import { tint } from '../domain/safety'

export function Panel({
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
    <section className={`panel overflow-hidden ${className}`}>
      <div className="flex items-center justify-between border-b border-outline-variant/40 px-4 py-2">
        <h2 className="heading-title">{title}</h2>
        {right}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

/** Uppercase monospace pill with an inline color accent. */
export function Badge({
  color,
  children,
  pulse = false,
}: {
  color: string
  children: ReactNode
  pulse?: boolean
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider"
      style={{ borderColor: color, color, background: tint(color, 0.1) }}
    >
      {pulse && <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: color }} />}
      {children}
    </span>
  )
}

export function StatTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="tile px-2 py-1.5 text-center">
      <p className="overline-label">{label}</p>
      <p className="copy-value" style={color ? { color } : undefined}>
        {value}
      </p>
    </div>
  )
}

export function KeyValue({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-outline-variant/20 py-1 last:border-0">
      <span className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {label}
      </span>
      <span className="font-mono text-xs text-on-surface" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  )
}

export function Empty({ label }: { label: string }) {
  return <p className="font-mono text-[11px] text-on-surface-variant">{label}</p>
}