import { useEffect, useRef } from 'react'
import { CLASS_COLOR, type Detection } from '../domain/detection'
import { expectedStep, stepForActivity } from '../domain/experiment'
import type { ExperimentState, ObjectKind, StepDef } from '../domain/types'
import { formatClock } from '../lib/time'

interface Rect {
  x: number
  y: number
  w: number
  h: number
}

const W = 960
const H = 540

const TABLE: Rect = { x: 80, y: 250, w: 800, h: 235 }
const TARGET: Rect = { x: 600, y: 268, w: 240, h: 165 }
const MAIN: Rect = { x: 265, y: 290, w: 155, h: 110 }
const SLOT_RED: Rect = { x: 282, y: 330, w: 40, h: 40 }
const SLOT_YEL: Rect = { x: 360, y: 330, w: 40, h: 40 }
const HAND_RED = { x: 540, y: 245 }
const HAND_YEL = { x: 582, y: 215 }
const PLACED_RED: Rect = { x: 645, y: 315, w: 46, h: 46 }
const PLACED_YEL: Rect = { x: 742, y: 352, w: 46, h: 46 }

const COLORS = {
  bg: '#0b1220',
  floor: '#0f172a',
  grid: 'rgba(148, 163, 184, 0.06)',
  table: '#1e293b',
  tableEdge: '#334155',
  target: 'rgba(250, 204, 21, 0.9)',
  targetFill: 'rgba(250, 204, 21, 0.07)',
  main: '#94a3b8',
  mainDark: '#64748b',
  red: '#ef4444',
  redDark: '#b91c1c',
  yellow: '#facc15',
  yellowDark: '#a16207',
  hand: 'rgba(203, 213, 225, 0.95)',
}

function roundedRect(ctx: CanvasRenderingContext2D, r: Rect, radius: number): void {
  const x = r.x
  const y = r.y
  const w = r.w
  const h = r.h
  const rr = Math.min(radius, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

function drawBox(
  ctx: CanvasRenderingContext2D,
  rect: Rect,
  fill: string,
  dark: string,
  label: string,
  glow: boolean,
  alpha = 1,
): void {
  ctx.save()
  if (alpha < 1) ctx.globalAlpha = alpha
  if (glow) {
    ctx.shadowColor = fill
    ctx.shadowBlur = 22
    ctx.strokeStyle = fill
    ctx.lineWidth = 2
    const g = { x: rect.x - 4, y: rect.y - 4, w: rect.w + 8, h: rect.h + 8 }
    roundedRect(ctx, g, 8)
    ctx.stroke()
  }
  roundedRect(ctx, rect, 5)
  ctx.fillStyle = dark
  ctx.fill()
  const inset = { x: rect.x + 3, y: rect.y + 3, w: rect.w - 6, h: rect.h - 6 }
  roundedRect(ctx, inset, 4)
  ctx.fillStyle = fill
  ctx.fill()
  ctx.fillStyle = 'rgba(0,0,0,0.28)'
  ctx.font = 'bold 11px ui-monospace, monospace'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, rect.x + rect.w / 2, rect.y + rect.h / 2 + 1)
  ctx.restore()
}

function drawMainBox(ctx: CanvasRenderingContext2D, opened: boolean, glow: boolean): void {
  ctx.save()
  if (glow) {
    ctx.shadowColor = COLORS.main
    ctx.shadowBlur = 20
    ctx.strokeStyle = COLORS.main
    ctx.lineWidth = 2
    const g = { x: MAIN.x - 4, y: MAIN.y - 4, w: MAIN.w + 8, h: MAIN.h + 8 }
    roundedRect(ctx, g, 9)
    ctx.stroke()
  }

  roundedRect(ctx, MAIN, 8)
  ctx.fillStyle = COLORS.mainDark
  ctx.fill()
  ctx.fillStyle = COLORS.main
  ctx.fillRect(MAIN.x + 3, MAIN.y + MAIN.h * 0.45, MAIN.w - 6, MAIN.h * 0.52)
  ctx.fillStyle = 'rgba(0,0,0,0.35)'
  ctx.fillRect(MAIN.x + 10, MAIN.y + MAIN.h * 0.55, MAIN.w - 20, MAIN.h * 0.34)

  if (opened) {
    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)'
    ctx.fillRect(MAIN.x + 10, MAIN.y + MAIN.h * 0.5, MAIN.w - 20, MAIN.h * 0.42)
    ctx.save()
    ctx.fillStyle = COLORS.main
    ctx.translate(MAIN.x + 8, MAIN.y + MAIN.h * 0.5)
    ctx.rotate(-1.15)
    ctx.fillRect(2, -3, 52, 9)
    ctx.restore()
    ctx.save()
    ctx.translate(MAIN.x + MAIN.w - 8, MAIN.y + MAIN.h * 0.5)
    ctx.rotate(1.15)
    ctx.fillRect(-54, -3, 52, 9)
    ctx.restore()
  } else {
    ctx.fillStyle = COLORS.main
    roundedRect(ctx, { x: MAIN.x + 3, y: MAIN.y + 3, w: MAIN.w - 6, h: MAIN.h * 0.45 }, 6)
    ctx.fill()
    ctx.strokeStyle = 'rgba(15,23,42,0.7)'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(MAIN.x + MAIN.w * 0.5 - 22, MAIN.y + 6)
    ctx.lineTo(MAIN.x + MAIN.w * 0.5 + 22, MAIN.y + 6)
    ctx.stroke()
  }
  ctx.restore()
}

/** Steps grouped by object, derived from the configurable experiment def. */
function stepsByObject(exp: ExperimentState['experiment']): Map<ObjectKind, StepDef[]> {
  const map = new Map<ObjectKind, StepDef[]>()
  for (const step of exp.steps) {
    const list = map.get(step.object) ?? []
    list.push(step)
    map.set(step.object, list)
  }
  return map
}

function hasAction(list: StepDef[], action: StepDef['action'], completed: string[]): boolean {
  return list.some(step => step.action === action && completed.includes(step.id))
}

export function SimulatedFeed({ state }: { state: ExperimentState }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = W * dpr
    canvas.height = H * dpr
    ctx.scale(dpr, dpr)

    const hand = { x: MAIN.x + MAIN.w / 2, y: MAIN.y + MAIN.h + 40 }

    function resolveObjectPos(s: ExperimentState, object: ObjectKind): Rect | null {
      if (!object) return null
      const completed = s.completedStepIds
      const steps = stepsByObject(s.experiment)
      if (object === 'MAIN_BOX') return MAIN
      if (object === 'RED_BOX') {
        if (hasAction(steps.get('RED_BOX') ?? [], 'PLACE', completed)) return PLACED_RED
        if (hasAction(steps.get('RED_BOX') ?? [], 'PICK', completed)) {
          return { x: HAND_RED.x - 20, y: HAND_RED.y - 20, w: 40, h: 40 }
        }
        return SLOT_RED
      }
      if (object === 'YELLOW_BOX') {
        if (hasAction(steps.get('YELLOW_BOX') ?? [], 'PLACE', completed)) return PLACED_YEL
        if (hasAction(steps.get('YELLOW_BOX') ?? [], 'PICK', completed)) {
          return { x: HAND_YEL.x - 20, y: HAND_YEL.y - 20, w: 40, h: 40 }
        }
        return SLOT_YEL
      }
      return null
    }

    function focusObject(s: ExperimentState): ObjectKind {
      const det = s.currentDetected
      if (!det?.activity) return null
      return stepForActivity(s.experiment, det.activity)?.object ?? null
    }

    let raf = 0
    let frame = 0

    const draw = () => {
      frame += 1
      const s = stateRef.current
      ctx.clearRect(0, 0, W, H)

      // Background floor
      ctx.fillStyle = COLORS.bg
      ctx.fillRect(0, 0, W, H)
      ctx.fillStyle = COLORS.floor
      ctx.fillRect(0, 230, W, H - 230)
      ctx.strokeStyle = COLORS.grid
      ctx.lineWidth = 1
      for (let x = 0; x <= W; x += 60) {
        ctx.beginPath()
        ctx.moveTo(x, 230)
        ctx.lineTo(x, H)
        ctx.stroke()
      }
      for (let y = 230; y <= H; y += 60) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(W, y)
        ctx.stroke()
      }

      // Table
      roundedRect(ctx, TABLE, 14)
      ctx.fillStyle = COLORS.table
      ctx.fill()
      ctx.strokeStyle = COLORS.tableEdge
      ctx.lineWidth = 2
      ctx.stroke()

      // Target area
      roundedRect(ctx, TARGET, 10)
      ctx.fillStyle = COLORS.targetFill
      ctx.fill()
      ctx.strokeStyle = COLORS.target
      ctx.lineWidth = 2
      ctx.setLineDash([8, 6])
      ctx.stroke()
      ctx.setLineDash([])
      ctx.fillStyle = COLORS.target
      ctx.font = 'bold 11px ui-monospace, monospace'
      ctx.textAlign = 'center'
      ctx.fillText('TARGET AREA', TARGET.x + TARGET.w / 2, TARGET.y - 8)

      const completed = s.completedStepIds
      const steps = stepsByObject(s.experiment)
      const mainSteps = steps.get('MAIN_BOX') ?? []
      const redSteps = steps.get('RED_BOX') ?? []
      const yellowSteps = steps.get('YELLOW_BOX') ?? []

      const opened = hasAction(mainSteps, 'OPEN', completed)
      const redPicked = hasAction(redSteps, 'PICK', completed)
      const redPlaced = hasAction(redSteps, 'PLACE', completed)
      const yellowPicked = hasAction(yellowSteps, 'PICK', completed)
      const yellowPlaced = hasAction(yellowSteps, 'PLACE', completed)
      const focus = focusObject(s)

      // Main box
      drawMainBox(ctx, opened, focus === 'MAIN_BOX' && s.status === 'RUNNING')

      // Inner boxes (visible once opened, before being picked)
      if (opened && !redPicked) drawBox(ctx, SLOT_RED, COLORS.red, COLORS.redDark, 'RED', focus === 'RED_BOX')
      if (opened && !yellowPicked) drawBox(ctx, SLOT_YEL, COLORS.yellow, COLORS.yellowDark, 'YEL', focus === 'YELLOW_BOX')

      // In-hand / placed boxes
      const inHandRed: Rect = { x: HAND_RED.x - 20, y: HAND_RED.y - 20, w: 40, h: 40 }
      const inHandYel: Rect = { x: HAND_YEL.x - 20, y: HAND_YEL.y - 20, w: 40, h: 40 }
      if (redPicked && !redPlaced) drawBox(ctx, inHandRed, COLORS.red, COLORS.redDark, 'RED', focus === 'RED_BOX')
      if (redPlaced) drawBox(ctx, PLACED_RED, COLORS.red, COLORS.redDark, 'RED', false)
      if (yellowPicked && !yellowPlaced) drawBox(ctx, inHandYel, COLORS.yellow, COLORS.yellowDark, 'YEL', focus === 'YELLOW_BOX')
      if (yellowPlaced) drawBox(ctx, PLACED_YEL, COLORS.yellow, COLORS.yellowDark, 'YEL', false)

      // Operator hand indicator
      const expected = s.status === 'RUNNING' ? expectedStep(s.experiment, s.currentStepIndex) : undefined
      const target = s.status === 'RUNNING' ? resolveObjectPos(s, expected?.object ?? null) : null
      const tx = target ? target.x + target.w / 2 : MAIN.x + MAIN.w / 2
      const ty = target ? target.y + target.h / 2 : MAIN.y + MAIN.h + 40
      hand.x += (tx - hand.x) * 0.08
      hand.y += (ty - hand.y) * 0.08
      const bob = Math.sin(frame / 9) * 4
      ctx.lineCap = 'round'
      ctx.strokeStyle = COLORS.hand
      ctx.lineWidth = 4
      ctx.beginPath()
      ctx.moveTo(hand.x + 26, hand.y + 14)
      ctx.lineTo(hand.x, hand.y + bob * 0.4)
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(hand.x, hand.y + bob, 11, 0, Math.PI * 2)
      ctx.fillStyle = COLORS.hand
      ctx.fill()

      // Detection chip
      const det = s.currentDetected
      if (s.status === 'RUNNING' && det?.activity) {
        ctx.fillStyle = 'rgba(2, 6, 23, 0.85)'
        roundedRect(ctx, { x: W / 2 - 150, y: 14, w: 300, h: 34 }, 8)
        ctx.fill()
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)'
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.fillStyle = '#e2e8f0'
        ctx.font = 'bold 13px ui-monospace, monospace'
        ctx.textAlign = 'center'
        const pct = Math.round(det.confidence * 100)
        ctx.fillText(`${det.activity.replace(/_/g, ' ')}  ·  ${pct}% conf`, W / 2, 36)
      }

      // Next-step prompt
      if (s.status === 'RUNNING' && expected) {
        ctx.fillStyle = 'rgba(16, 185, 129, 0.9)'
        ctx.font = 'bold 13px ui-monospace, monospace'
        ctx.textAlign = 'center'
        ctx.fillText(`NEXT: ${expected.label.toUpperCase()}`, W / 2, H - 18)
      }

      // Overlays
      ctx.fillStyle = 'rgba(148, 163, 184, 0.85)'
      ctx.font = 'bold 11px ui-monospace, monospace'
      ctx.textAlign = 'left'
      ctx.fillText('CAM-01 · SIMULATED FEED', 14, 24)
      if (s.recording) {
        if (frame % 40 < 22) {
          ctx.fillStyle = '#f43f5e'
          ctx.beginPath()
          ctx.arc(W - 26, 22, 6, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.fillStyle = '#fda4af'
        ctx.fillText('REC', W - 14, 27)
      }
      ctx.fillStyle = 'rgba(148, 163, 184, 0.6)'
      ctx.fillText(formatClock(Date.now()), 14, H - 14)

      if (s.status !== 'RUNNING') {
        ctx.fillStyle = 'rgba(2, 6, 23, 0.62)'
        ctx.fillRect(0, 0, W, H)
        ctx.fillStyle = '#e2e8f0'
        ctx.font = 'bold 20px ui-monospace, monospace'
        ctx.textAlign = 'center'
        ctx.fillText(s.status === 'COMPLETED' ? 'EXPERIMENT COMPLETE' : 'STANDBY — PRESS START', W / 2, H / 2 - 8)
        ctx.fillStyle = 'rgba(226, 232, 240, 0.6)'
        ctx.font = '13px ui-monospace, monospace'
        ctx.fillText(
          s.status === 'COMPLETED' ? 'All steps logged successfully.' : 'Camera feed waiting for operator.',
          W / 2,
          H / 2 + 18,
        )
      }

      raf = requestAnimationFrame(draw)
    }

    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-200 dark:border-slate-800 dark:bg-slate-950">
      <canvas ref={canvasRef} className="block aspect-video w-full" />
    </div>
  )
}

/** Stand-in for the canvas simulation when a real camera stream is live. */
export function LiveCameraFeed({
  streamUrl,
  detections = [],
  unknownDetections = [],
  frameWidth = null,
  frameHeight = null,
}: {
  streamUrl: string
  detections?: Detection[]
  unknownDetections?: Detection[]
  frameWidth?: number | null
  frameHeight?: number | null
}) {
  const showBoxes = frameWidth != null && frameHeight != null && frameWidth > 0 && frameHeight > 0
  const all = [...detections, ...unknownDetections]
  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-200 dark:border-slate-800 dark:bg-slate-950">
      <img
        src={streamUrl}
        alt="Live camera feed"
        className="block aspect-video w-full object-cover"
      />
      {showBoxes && (
        <div className="pointer-events-none absolute inset-0">
          {all.map((d, i) => {
            const isUnknown = d.class_name === 'unknown_object'
            const left = (d.x1 / (frameWidth as number)) * 100
            const top = (d.y1 / (frameHeight as number)) * 100
            const width = ((d.x2 - d.x1) / (frameWidth as number)) * 100
            const height = ((d.y2 - d.y1) / (frameHeight as number)) * 100
            return (
              <div
                key={i}
                className="absolute rounded border-2"
                style={{
                  left: `${left}%`,
                  top: `${top}%`,
                  width: `${width}%`,
                  height: `${height}%`,
                  borderColor: isUnknown ? '#ffffff' : CLASS_COLOR[d.class_name] ?? '#38bdf8',
                  borderStyle: isUnknown ? 'dashed' : 'solid',
                }}
              >
                <span
                  className={`absolute -top-5 left-0 rounded px-1 py-0.5 font-mono text-[10px] font-bold tracking-wide ${
                    isUnknown ? 'bg-white/85 text-slate-900' : 'bg-black/70 text-slate-100'
                  }`}
                >
                  {isUnknown ? (d.instance_id ?? 'unknown') : d.class_name.replace(/_/g, ' ')}{' '}
                  {Math.round(d.confidence * 100)}%
                </span>
              </div>
            )
          })}
        </div>
      )}
      <span className="absolute left-3.5 top-3 rounded bg-black/55 px-2 py-0.5 font-mono text-[11px] font-bold tracking-wide text-slate-200">
        CAM-01 · LIVE FEED
      </span>
    </div>
  )
}

export function LiveFeed({
  state,
  streamUrl,
  detections = [],
  unknownDetections = [],
  frameWidth = null,
  frameHeight = null,
}: {
  state: ExperimentState
  streamUrl?: string | null
  detections?: Detection[]
  unknownDetections?: Detection[]
  frameWidth?: number | null
  frameHeight?: number | null
}) {
  if (streamUrl) {
    return (
      <LiveCameraFeed
        streamUrl={streamUrl}
        detections={detections}
        unknownDetections={unknownDetections}
        frameWidth={frameWidth}
        frameHeight={frameHeight}
      />
    )
  }
  return <SimulatedFeed state={state} />
}