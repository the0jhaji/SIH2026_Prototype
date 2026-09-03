export type ViewKey =
  | 'experiments'
  | 'live'
  | 'sequence'
  | 'logs'
  | 'analytics'
  | 'system'

export interface NavItem {
  key: ViewKey
  icon: string
  label: string
}

export const NAV_ITEMS: NavItem[] = [
  { key: 'experiments', icon: 'science', label: 'Exp' },
  { key: 'live', icon: 'videocam', label: 'Live' },
  { key: 'sequence', icon: 'list_alt', label: 'Seq' },
  { key: 'logs', icon: 'terminal', label: 'Logs' },
  { key: 'analytics', icon: 'query_stats', label: 'Stats' },
  { key: 'system', icon: 'memory', label: 'System' },
]

export const VIEW_TITLES: Record<ViewKey, string> = {
  experiments: 'Experiment Configuration',
  live: 'Live Monitor',
  sequence: 'Sequence Validation',
  logs: 'Experiment Logs',
  analytics: 'Analytics & Telemetry',
  system: 'System Core Monitoring',
}
