function pad(n: number, width = 2): string {
  return String(n).padStart(width, '0')
}

/** Compact wall-clock time, e.g. 14:03:22 */
export function formatClock(ts: number): string {
  const d = new Date(ts)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** Wall-clock with milliseconds, used by the event log. */
export function formatTimestamp(ts: number): string {
  const d = new Date(ts)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}