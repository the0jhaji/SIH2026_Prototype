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
  camera: 'Live Observation',
  assessment: 'Hazard Assessment',
  astronaut: 'Crew Status',
  alerts: 'Active Alerts',
  station: 'Station Systems',
  escalation: 'Earth Escalation',
  incidents: 'Mission Logs',
  experiments: 'Experiment Demo',
}

/**
 * Per-view information density. Set once on the shell as `data-density`;
 * every card, gap and page padding derives from it, so a dense monitoring
 * screen and a media-focused screen stay consistent without per-card
 * styling. Monitoring views are compact, the camera and experiment views
 * give their imagery room, the rest are normal.
 */
export type Density = 'compact' | 'normal' | 'focus'

export const VIEW_DENSITY: Record<ViewKey, Density> = {
  mission: 'compact',
  camera: 'focus',
  assessment: 'normal',
  astronaut: 'normal',
  alerts: 'normal',
  station: 'normal',
  escalation: 'normal',
  incidents: 'normal',
  experiments: 'focus',
}
