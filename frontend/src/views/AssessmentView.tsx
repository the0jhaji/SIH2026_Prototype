import { useMemo } from 'react'
import { RISK_COLORS, safeCount, safePercent, tint } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import { HazardCard } from './MissionView'
import { Badge, EmptyState, MetricCard, Panel, SectionHeader, StatTile, SubCard } from './ui'
import { PageShell, Timeline } from './layout'
import { safetyEventEntries, relativeAge } from './helpers'
import type { SafetyCommonProps } from './props'

const RISK_BANDS = [
  { level: 'CRITICAL', range: '≥ 80%' },
  { level: 'WARNING', range: '55–79%' },
  { level: 'CAUTION', range: '30–54%' },
  { level: 'SAFE', range: '< 30%' },
] as const

/**
 * Hazard board.
 *
 * A severity summary strip, the assessments themselves, the risk context
 * beside them, and the transition history underneath. With no hazards the
 * board still carries the full context — the empty state says the
 * environment is clean rather than leaving the lower half of the screen
 * blank.
 */
export function AssessmentView({ safety }: SafetyCommonProps) {
  const snapshot = safety.snapshot
  const assessments = snapshot?.assessments ?? []
  const hazards = assessments.filter(a => a.hazard)
  const unclassified = snapshot?.unclassified ?? []
  const timeline = useMemo(() => safetyEventEntries(safety.events, 60), [safety.events])

  const count = (level: string) =>
    assessments.filter(a => a.risk_level === level).length
  const critical = count('CRITICAL') + count('HIGH')
  const warning = count('WARNING')
  const caution = count('CAUTION')
  const safe = count('SAFE')

  return (
    <PageShell>
      {/* ── Severity summary ─────────────────────────────────────── */}
      <div className="grid shrink-0 grid-cols-2 gap-[var(--grid-gap)] lg:grid-cols-4">
        <MetricCard
          label="Critical"
          value={String(critical)}
          sub={`${hazards.length} hazardous`}
          color={RISK_COLORS.CRITICAL}
          active={critical > 0}
        />
        <MetricCard
          label="Warning"
          value={String(warning)}
          sub="objects at 55–79%"
          color={RISK_COLORS.WARNING}
          active={warning > 0}
        />
        <MetricCard
          label="Caution"
          value={String(caution)}
          sub="objects at 30–54%"
          color={RISK_COLORS.CAUTION}
          active={caution > 0}
        />
        <MetricCard
          label="Safe"
          value={String(safe)}
          sub={`${safePercent(assessments)} of assessed`}
          color={RISK_COLORS.SAFE}
          active={critical + warning === 0}
        />
      </div>

      {/* ── Assessments + risk context ────────────────────────────── */}
      <div className="page-fill grid-cols-1 lg:grid-cols-[minmax(0,1.95fr)_minmax(0,1fr)]">
        <Panel
          title="Hazard Assessments"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {hazards.length} / {assessments.length} hazardous
            </span>
          }
        >
          {assessments.length === 0 ? (
            <EmptyState
              icon="verified_user"
              title="No active hazards"
              description="Environment currently has no confirmed hazards."
              status={
                safety.offline
                  ? 'Backend offline — polling'
                  : snapshot?.feed_stale
                    ? 'Feed stale'
                    : undefined
              }
              lastUpdated={
                snapshot?.timestamp ? `Last assessment ${formatTimestamp(snapshot.timestamp)}` : undefined
              }
            />
          ) : (
            <div className="rows">
              {assessments.map(a => (
                <HazardCard key={`${a.object}-${a.timestamp}`} assessment={a} />
              ))}
            </div>
          )}
        </Panel>

        <div className="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Current Risk"
            right={
              <Badge color={RISK_COLORS[snapshot?.overall_risk_level ?? 'SAFE']}>
                {snapshot?.overall_risk_level ?? '—'}
              </Badge>
            }
          >
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                  Overall risk score
                </p>
                <p
                  className="font-mono text-3xl font-bold leading-none"
                  style={{ color: RISK_COLORS[snapshot?.overall_risk_level ?? 'SAFE'] }}
                >
                  {Math.round((snapshot?.overall_risk_score ?? 0) * 100)}%
                </p>
              </div>
              <div className="grid grid-cols-2 gap-[var(--row-pad)]">
                <StatTile label="Assessed" value={String(assessments.length)} />
                <StatTile
                  label="Safe"
                  value={String(safeCount(assessments))}
                  color={RISK_COLORS.SAFE}
                />
              </div>
            </div>
            <div className="mt-2 h-1.5 w-full bg-surface-container-high">
              <div
                className="h-full transition-all"
                style={{
                  width: `${Math.min(100, Math.round((snapshot?.overall_risk_score ?? 0) * 100))}%`,
                  background: RISK_COLORS[snapshot?.overall_risk_level ?? 'SAFE'],
                }}
              />
            </div>
          </Panel>

          <Panel title="Risk Scale">
            <ul className="rows">
              {RISK_BANDS.map(band => (
                <li
                  key={band.level}
                  className="flex items-center justify-between border px-2 py-1"
                  style={{
                    borderLeftWidth: 3,
                    borderLeftColor: RISK_COLORS[band.level],
                    borderTopColor: 'color-mix(in oklab, var(--t-outline-variant) 40%, transparent)',
                    borderRightColor: 'color-mix(in oklab, var(--t-outline-variant) 40%, transparent)',
                    borderBottomColor: 'color-mix(in oklab, var(--t-outline-variant) 40%, transparent)',
                  }}
                >
                  <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                    {band.level}
                  </span>
                  <span className="font-mono text-[10px] text-on-surface-variant">{band.range}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 font-mono text-[10px] leading-snug text-on-surface-variant">
              A single unframed sighting is capped at CAUTION until it is temporally confirmed.
            </p>
          </Panel>

          <Panel title="Environment" fill scroll>
            <div className="stack">
              <SubCard title="Mode">
                <p className="font-mono text-sm font-semibold">
                  {snapshot?.environment_mode ?? '—'}
                </p>
                <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                  Operational config — never inferred from pixels.
                </p>
              </SubCard>

              <SubCard
                title="Unclassified objects"
                right={
                  <span className="font-mono text-[10px] text-on-surface-variant">
                    {unclassified.length}
                  </span>
                }
              >
                {unclassified.length === 0 ? (
                  <p className="font-mono text-[10px] leading-snug text-on-surface-variant">
                    Every detected class is known to the hazard knowledge base.
                  </p>
                ) : (
                  <ul className="flex flex-wrap gap-1">
                    {unclassified.map(name => (
                      <li
                        key={name}
                        className="border border-outline-variant/50 bg-surface-container-low px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant"
                      >
                        {name.replace(/_/g, ' ')}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-1 font-mono text-[10px] leading-snug text-on-surface-variant">
                  Unclassified classes get no hazard claim — the system never guesses.
                </p>
              </SubCard>

              <SubCard title="Assessment freshness">
                <p className="font-mono text-[10px] text-on-surface">
                  {snapshot?.timestamp
                    ? `${formatTimestamp(snapshot.timestamp)} · ${relativeAge(snapshot.timestamp)}`
                    : 'No assessment received'}
                </p>
                <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                  {snapshot?.feed_stale
                    ? 'Feed is stale — the last known scene is retained and nothing new is claimed.'
                    : 'Live assessment from the current frame.'}
                </p>
              </SubCard>

              <SubCard title="Risk history">
                <SectionHeader title="Recent transitions" />
                <Timeline
                  entries={timeline.slice(0, 24)}
                  empty={
                    <p className="font-mono text-[10px] text-on-surface-variant">
                      No hazard transitions recorded yet.
                    </p>
                  }
                />
              </SubCard>
            </div>
          </Panel>
        </div>
      </div>

      {/* ── Bottom strip: environment-wide context ───────────────── */}
      <div
        className="page-fill shrink-0 grid-cols-1 md:grid-cols-3"
        style={{ height: 'var(--strip-h)', flex: 'none' }}
      >
        <Panel
          title="Risk Timeline"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {timeline.length} events
            </span>
          }
        >
          <Timeline
            entries={timeline}
            empty={
              <EmptyState
                compact
                icon="history"
                title="No transitions yet"
                description="The safety monitor has not changed state."
              />
            }
          />
        </Panel>

        <Panel
          title="Resolved Hazards"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {safety.alerts.filter(a => a.resolved).length} resolved
            </span>
          }
        >
          {safety.alerts.filter(a => a.resolved).length === 0 ? (
            <EmptyState
              compact
              icon="task_alt"
              title="No resolved hazards"
              description="An alert moves here once the hazard it describes is no longer confirmed."
            />
          ) : (
            <ul className="rows">
              {safety.alerts
                .filter(a => a.resolved)
                .map(a => (
                  <li
                    key={a.id}
                    className="flex items-center justify-between gap-2 border px-2 py-1"
                    style={{ borderLeftWidth: 3, borderLeftColor: tint(RISK_COLORS.SAFE, 0.6) }}
                  >
                    <span className="min-w-0 truncate font-mono text-[11px] uppercase tracking-wider">
                      {a.object ?? a.event_type.replace(/_/g, ' ')}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-on-surface-variant">
                      {formatTimestamp(a.resolved_at ?? a.updated_at)}
                    </span>
                  </li>
                ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="Hazard Knowledge Base"
          fill
          scroll
          right={
            <Badge color="#38bdf8">{snapshot?.model_version ?? 'model —'}</Badge>
          }
        >
          <div className="stack">
            <SubCard title="Rating source">
              <p className="font-mono text-[10px] leading-snug text-on-surface-variant">
                Class ratings come from the backend knowledge base (hazards.json), never from a
                hardcoded list in the UI. The current detector is{' '}
                <span className="text-on-surface">{snapshot?.detector ?? 'unknown'}</span>.
              </p>
            </SubCard>
            <SubCard title="Class coverage">
              <p className="font-mono text-[10px] text-on-surface-variant">
                {assessments.length === 0
                  ? 'No objects are being assessed, so no class has a risk rating this frame.'
                  : `${assessments.length} class${assessments.length === 1 ? '' : 'es'} rated this frame: ${assessments
                      .map(a => `${a.object} ${a.risk_level}`)
                      .join(' · ')}`}
              </p>
            </SubCard>
            <SubCard title="Monitor">
              <p className="font-mono text-[10px] text-on-surface-variant">
                State <span className="text-on-surface">{snapshot?.monitor.state ?? '—'}</span> (index{' '}
                {snapshot?.monitor.stateIndex ?? 0}) · {snapshot?.monitoring ? 'monitoring' : 'not monitoring'}
              </p>
            </SubCard>
          </div>
        </Panel>
      </div>
    </PageShell>
  )
}
