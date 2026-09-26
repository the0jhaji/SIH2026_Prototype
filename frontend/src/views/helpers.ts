import { useMemo, useState } from 'react'
import { ALERT_COLORS, MISSION_COLORS, type AlertLevel, type SafetyEvent } from '../domain/safety'
import type { AttendanceEvent } from '../domain/attendance'
import type { BasEvent } from '../domain/types'
import { formatClock, formatTimestamp } from '../lib/time'

/**
 * Derived view helpers.
 *
 * These live outside `layout.tsx` on purpose: that file exports React
 * components, and a module that mixes components with plain functions breaks
 * fast refresh. Nothing here renders — it only maps backend payloads onto
 * the shared palette and the timeline shape.
 */

const NEUTRAL = '#64748b'

/** Map any backend severity/level string onto the shared operational palette. */
export function severityColor(severity: string | null | undefined): string {
  if (!severity) return NEUTRAL
  const key = severity.toUpperCase()
  if (key in ALERT_COLORS) return ALERT_COLORS[key as AlertLevel]
  if (key === 'HIGH' || key === 'ERROR') return '#ef4444'
  if (key === 'WARN' || key === 'WARNING') return '#f97316'
  if (key === 'OK' || key === 'SAFE' || key === 'NORMAL') return '#22c55e'
  if (key === 'INFO') return '#38bdf8'
  return NEUTRAL
}

export function stateColor(state: string | null | undefined): string {
  if (!state) return NEUTRAL
  return MISSION_COLORS[state as keyof typeof MISSION_COLORS] ?? NEUTRAL
}

/** CSS text utility for a severity, for use with Tailwind's own classes. */
export function severityTextClass(severity: string | null | undefined): string {
  const key = (severity ?? '').toUpperCase()
  if (key === 'ERROR' || key === 'CRITICAL' || key === 'EMERGENCY') return 'text-error'
  if (key === 'WARN' || key === 'WARNING' || key === 'HIGH') return 'text-warning'
  if (key === 'OK' || key === 'SAFE') return 'text-secondary'
  return 'text-on-surface-variant'
}

export interface TimelineEntry {
  id: string
  ts: number
  color: string
  title: string
  detail?: string
  meta?: string
}

/** Safety engine event log → timeline entries. */
export function safetyEventEntries(events: SafetyEvent[] | undefined, limit = 40): TimelineEntry[] {
  return (events ?? []).slice(0, limit).map(e => ({
    id: `safety-${e.seq}`,
    ts: e.ts,
    color: severityColor(e.severity),
    title: String(e.kind).replace(/_/g, ' '),
    detail: e.message,
    meta: e.level ? `level ${String(e.level)}` : undefined,
  }))
}

/** Attendance (held / released / unattended) chain → timeline entries. */
export function attendanceEventEntries(
  events: AttendanceEvent[] | undefined,
  limit = 40,
): TimelineEntry[] {
  return (events ?? [])
    .slice(-limit)
    .reverse()
    .map((e, i) => ({
      id: `att-${e.ts}-${i}`,
      ts: e.ts,
      color: severityColor(e.severity),
      title: e.kind.replace(/_/g, ' '),
      detail: e.message ?? e.reason,
      meta: [e.object, e.from && e.to ? `${e.from} → ${e.to}` : null].filter(Boolean).join(' · ') || undefined,
    }))
}

/** Experiment state-machine log → timeline entries. */
export function basEventEntries(log: BasEvent[] | undefined, limit = 40): TimelineEntry[] {
  return (log ?? [])
    .slice(-limit)
    .reverse()
    .map(e => ({
      id: `bas-${e.seq}`,
      ts: e.ts,
      color: severityColor(e.severity),
      title: e.kind.replace(/_/g, ' '),
      detail: e.message,
      meta: [
        e.result,
        e.activity,
        e.expected,
        e.confidence != null ? `${Math.round(e.confidence * 100)}%` : null,
      ]
        .filter(Boolean)
        .join(' · ') || undefined,
    }))
}

/** "1m 04s ago" for a millisecond stamp; `—` when the source has none. */
export function relativeAge(ts: number | null | undefined, now = Date.now()): string {
  if (ts == null || !Number.isFinite(ts)) return '—'
  const delta = Math.max(0, now - ts)
  if (delta < 1000) return 'now'
  const s = Math.floor(delta / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s ago`
  const h = Math.floor(m / 60)
  return `${h}h ${String(m % 60).padStart(2, '0')}m ago`
}

/** Latest timestamp in a set, for an honest "last updated" label. */
export function latestTs(...stamps: (number | null | undefined)[]): number | null {
  const valid = stamps.filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  return valid.length ? Math.max(...valid) : null
}

/** Selection helper so list views keep a valid row across filter changes. */
export function useSelection<T>(rows: readonly T[], key: (row: T) => string) {
  const [selected, setSelected] = useState<string | null>(null)
  const active = useMemo(() => {
    if (selected && rows.some(r => key(r) === selected)) return selected
    return rows.length ? key(rows[0]) : null
  }, [rows, selected, key])
  return { selected: active, select: setSelected }
}

export { formatClock, formatTimestamp }
