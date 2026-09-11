export type ViewKey =
  | 'mission'
  | 'camera'
  | 'assessment'
  | 'astronaut'
  | 'alerts'
  | 'station'
  | 'escalation'
  | 'incidents'
  | 'experiments'

export interface NavItem {
  key: ViewKey
  icon: string
  label: string
}

export const NAV_ITEMS: NavItem[] = [
  { key: 'mission', icon: 'radar', label: 'Mission' },
  { key: 'camera', icon: 'videocam', label: 'Camera' },
  { key: 'assessment', icon: 'warning', label: 'Hazards' },
  { key: 'astronaut', icon: 'accessibility_new', label: 'Crew' },
  { key: 'alerts', icon: 'notifications', label: 'Alerts' },
  { key: 'station', icon: 'router', label: 'Station' },
  { key: 'escalation', icon: 'public', label: 'Earth' },
  { key: 'incidents', icon: 'history_edu', label: 'Logs' },
  { key: 'experiments', icon: 'science', label: 'Demo' },
]

export const VIEW_TITLES: Record<ViewKey, string> = {
  mission: 'Mission Status',
  camera: 'Live Camera & Detection',
  assessment: 'Hazard Assessment',
  astronaut: 'Astronaut Status',
  alerts: 'Active Alerts',
  station: 'Mission Control / Space Station',
  escalation: 'Earth Escalation',
  incidents: 'Incident History',
  experiments: 'Legacy Experiment Demo',
}