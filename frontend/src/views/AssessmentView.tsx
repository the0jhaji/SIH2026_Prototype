import { RISK_COLORS, safeCount } from '../domain/safety'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, Panel } from './ui'
import { HazardCard } from './MissionView'

export function AssessmentView({ safety }: SafetyCommonProps) {
  const assessments = safety.snapshot?.assessments ?? []
  const hazards = assessments.filter(a => a.hazard)
  const unclassified = safety.snapshot?.unclassified ?? []

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-4">
        <Panel
          title="Hazard Assessments"
          right={
            <span className="font-mono text-[10px] uppercase text-on-surface-variant">
              {hazards.length} / {assessments.length} hazardous
            </span>
          }
        >
          {assessments.length === 0 ? (
            <Empty
              label={
                safety.offline
                  ? 'Backend offline — polling for a mission snapshot.'
                  : safety.snapshot?.feed_stale
                    ? 'Feed is stale (camera stopped). Last known assessment retained.'
                    : 'No objects in view — waiting for a detection.'
              }
            />
          ) : (
            <ul className="space-y-2">
              {assessments.map(a => (
                <li key={a.object}>
                  <HazardCard assessment={a} />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Unclassified Objects">
          {unclassified.length === 0 ? (
            <Empty label="Nothing unclassified — every detected class is known to the hazard KB." />
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {unclassified.map(name => (
                <li
                  key={name}
                  className="border border-outline-variant/50 bg-surface-container-low px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-on-surface-variant"
                >
                  {name.replace(/_/g, ' ')}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
            Unclassified classes get no hazard claim — the system never guesses.
          </p>
        </Panel>
      </div>

      <div className="space-y-4">
        <Panel title="Risk Scale">
          <ul className="mt-1 space-y-2">
            {(['CRITICAL', 'WARNING', 'CAUTION', 'SAFE'] as const).map(level => (
              <li
                key={level}
                className="flex items-center justify-between border border-outline-variant/30 bg-surface-container-low px-2.5 py-1.5"
              >
                <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                  {level}
                </span>
                <Badge color={RISK_COLORS[level]}>
                  {level === 'CRITICAL'
                    ? '≥ 80%'
                    : level === 'WARNING'
                      ? '55–79%'
                      : level === 'CAUTION'
                        ? '30–54%'
                        : '< 30%'}
                </Badge>
              </li>
            ))}
          </ul>
          <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
            One unframed sighting is capped at CAUTION until temporally confirmed.
          </p>
        </Panel>

        <Panel title="Environment">
          <p className="mt-1 font-mono text-xs text-on-surface">
            {safety.snapshot?.environment_mode ?? '—'}
          </p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
            Operational config — never inferred from pixels.
          </p>
          <p className="mt-2 font-mono text-[11px] text-on-surface-variant">
            Top risk level: {safety.snapshot?.overall_risk_level ?? 'SAFE'} ·{' '}
            {safeCount(safety.snapshot?.assessments)} of {safety.snapshot?.assessments?.length ?? 0} assessed objects safe
          </p>
        </Panel>
      </div>
    </div>
  )
}