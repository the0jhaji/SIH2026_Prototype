/** Mirror of the backend detection payloads (camelCase JSON). */

import type { AttendanceWatch } from './attendance'
import type { HazardAssessment, RiskLevel } from './safety'

/**
 * The one detection shape the whole app uses.
 *
 * There is deliberately no separate "unknown detection" type: the backend
 * reports generic proposals on the very same contract (only
 * `class_name === UNKNOWN_CLASS` differs), and a second structurally
 * identical interface is how a `Detection[]` and an `UnknownDetection[]` end
 * up unable to be concatenated in the view layer.
 */
export interface Detection {
  class_name: string
  confidence: number
  x1: number
  y1: number
  x2: number
  y2: number
  timestamp: number
  /** Stable per-track id for generic/unknown objects (e.g. "unknown-1"). */
  instance_id?: string
  /**
   * Speculative open-vocabulary label for a track (e.g. "bottle"). Optional
   * and *unconfirmed*: it is rendered as `POSSIBLE BOTTLE`, never as a fact.
   * Undefined today — populated by the classifier that plugs into the unknown
   * track seam later.
   */
  possible_label?: string
}

export type DetectionInferenceStatus = 'disabled' | 'idle' | 'ok' | 'error'

/**
 * Compact structured-trace summary from `ai/detection/detect_log.py`, embedded in
 * the status payload only while tracing is enabled. Latest duration per pipeline
 * stage plus a bounded event rate — the history itself lives behind
 * `GET /api/detection/trace` so this per-second payload stays small.
 *
 * `errors` counts failures *of the tracer itself*. It must be 0; a non-zero
 * value means the diagnostics are silently broken, which is worse than no trace.
 */
export interface TraceStats {
  level: string
  enabled: boolean
  textLogEnabled?: boolean
  bufferSize: number
  bufferCapacity: number
  eventsTotal: number
  eventsPerSecond: number
  errors: number
  lastPipelineMs: number | null
  captureMs: number | null
  yoloMs: number | null
  unknownDetectorMs: number | null
  trackerMs: number | null
  openclipMs: number | null
  hazardMs: number | null
  stages?: Record<string, number>
}

export interface DetectionStatus {
  enabled: boolean
  detector: string | null
  modelLoaded: boolean
  modelPath: string | null
  modelSizeMb: number | null
  /** Number of classes the loaded model can actually emit. */
  classCount: number | null
  /** False = narrow/specialised vocabulary (e.g. red_box+yellow_box only). */
  generalPurpose: boolean | null
  inputSize: number | null
  iouThreshold: number | null
  classes: string[] | null
  confThreshold: number
  unknownEnabled: boolean
  unknownMode: string | null
  inferenceStatus: DetectionInferenceStatus
  lastInference: number | null
  detectionCount: number
  rawDetectionCount: number
  unknownCount: number
  /** Configured AI rate cap; 0 = uncapped. Camera FPS is independent. */
  targetFps: number
  /** Measured AI inferences/sec over the last window. */
  actualFps: number
  /** Total inferences performed by the service thread. */
  inferenceCount: number
  /** Camera frames dropped because the rate gate was not due yet (never queued). */
  skippedForRate: number
  /** Structured ring-buffer trace is on (cheap; `DETECT_TRACE_LEVEL != OFF`). */
  traceEnabled: boolean
  /** Configured trace verbosity; `OFF` when tracing is disabled. */
  traceLevel?: string
  /** Legacy per-candidate text log (expensive, separate switch, off by default). */
  textLogEnabled?: boolean
  /** Present only while `traceEnabled` — see {@link TraceStats}. */
  trace?: TraceStats
  error: string | null
}

export interface DetectionResult {
  enabled: boolean
  /**
   * Pixel size of the frame the detections below were computed on. The
   * overlay divides by exactly these numbers; the browser viewport is
   * irrelevant to the mapping. Null only while no frame is being served.
   */
  frameWidth: number | null
  frameHeight: number | null
  /** Provenance of the frame size: `inference` | `camera` | `disabled` | `unknown`. */
  frameSizeSource?: FrameSizeSource
  /** Debounced + EMA-smoothed view (what safety consumes). */
  detections: Detection[]
  /** Current-frame, unfiltered detections (debugging). */
  rawDetections: Detection[]
  unknownDetections: Detection[]
  rawUnknownDetections: Detection[]
  lastInferenceMs: number | null
  inferenceMs: number | null
  inferenceStatus: DetectionInferenceStatus
  error: string | null
}

export interface DetectionBoxOverlay {
  detections: Detection[]
  unknownDetections?: Detection[]
  frameWidth: number | null
  frameHeight: number | null
}

// ---------------------------------------------------------------- overlay

/** The class name the generic proposer reports; one source, not a literal per view. */
export const UNKNOWN_CLASS = 'unknown_object'

/**
 * Overlay style per detection. The distinction drives colour, dash pattern and
 * z-order, so "unknown" and "hazard" can never collapse into the same box:
 *   known      — recognised class, nothing wrong with it        (green, solid)
 *   hazard     — recognised class the safety KB rates hazardous (red, solid)
 *   unknown    — unclassified proposal                           (orange, dashed)
 *   unattended — unknown proposal the attendance monitor gave up on (red, dashed)
 */
export type BoxStyle = 'known' | 'hazard' | 'unknown' | 'unattended'

export const BOX_COLORS: Record<BoxStyle, string> = {
  known: '#22c55e',
  hazard: '#ef4444',
  unknown: '#f97316',
  unattended: '#ef4444',
}

export const BOX_DASHED: Record<BoxStyle, boolean> = {
  known: false,
  hazard: false,
  unknown: true,
  unattended: true,
}

/** A box must be at least this many frame-pixels on both axes to be drawn. */
const MIN_BOX_PX = 2

/**
 * An unknown proposal that is really the same object as a recognised
 * detection. The backend already suppresses these before they reach the
 * tracker, but the two debounce windows are independent so a pair can still
 * slip through; drawing both would put a duplicate orange box over a green
 * `person`.
 *
 * Deliberately the SAME test as `DetectionService._overlaps_known` — IoU over
 * a floor, or either centre inside the other box. A plain
 * intersection-over-smaller is wrong here: a small motion blob overlapping the
 * bottom of a large person box scores high while being an entirely different
 * region of the frame, and would erase a real unknown object.
 */
const UNKNOWN_DUPLICATE_IOU = 0.35

export interface FrameSize {
  width: number
  height: number
}

export type FrameSizeSource = 'inference' | 'camera' | 'disabled' | 'unknown'

/** Extra signal the overlay needs that does not live on the detection itself. */
export interface OverlayContext {
  /**
   * class name -> risk level, taken from the safety snapshot (itself derived
   * from `hazards.json`). Never a hardcoded class list here: the knowledge base
   * is the single authority on what counts as a hazard.
   */
  hazardLevels?: Record<string, RiskLevel> | null
  /** instance ids of unknown objects the attendance monitor reports UNATTENDED. */
  unattendedIds?: ReadonlySet<string> | null
}

/** One drawable box, already in percent of the detection frame. */
export interface OverlayBox {
  key: string
  className: string
  instanceId: string | null
  style: BoxStyle
  color: string
  dashed: boolean
  /** Everything the label chip shows, e.g. `UNKNOWN OBJECT • 61% • unknown-100`. */
  text: string
  confidence: number
  /** Percent of the detection frame. Clamped, so never out of 0..100. */
  left: number
  top: number
  width: number
  height: number
  /** False when the box hugs the top edge and the chip must render inside. */
  labelAbove: boolean
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

/** True when a coordinate is a usable number at all (guards `null`/`'x'`/NaN). */
function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function pct(value: number): string {
  return `${Math.round(clamp(value, 0, 1) * 100)}%`
}

/**
 * Validate the detection frame. Anything that is not a positive, finite pair
 * means "no coordinate system to draw in" — the overlay renders nothing rather
 * than dividing by a garbage denominator.
 */
export function resolveFrameSize(
  frameWidth: number | null | undefined,
  frameHeight: number | null | undefined,
): FrameSize | null {
  if (typeof frameWidth !== 'number' || typeof frameHeight !== 'number') return null
  if (!Number.isFinite(frameWidth) || !Number.isFinite(frameHeight)) return null
  if (frameWidth <= 0 || frameHeight <= 0) return null
  return { width: Math.round(frameWidth), height: Math.round(frameHeight) }
}

function labelFor(d: Detection, style: BoxStyle, risk: RiskLevel | null): string {
  const confidence = pct(d.confidence)
  const instance = d.instance_id ?? '—'
  if (style === 'unattended') {
    return `UNATTENDED OBJECT • ${confidence} • ${instance}`
  }
  if (d.class_name === UNKNOWN_CLASS) {
    // A speculative open-vocabulary label is shown as a possibility, never as
    // an identification: the classifier has not confirmed anything.
    const name = d.possible_label
      ? `POSSIBLE ${d.possible_label.replace(/_/g, ' ').toUpperCase()}`
      : 'UNKNOWN OBJECT'
    return `${name} • ${confidence} • ${instance}`
  }
  const name = d.class_name.replace(/_/g, ' ')
  if (style === 'hazard') {
    return `${name.toUpperCase()} • ${confidence} • ${risk ?? 'HAZARD'}`
  }
  return `${name.toUpperCase()} • ${confidence}`
}

/**
 * Convert one detection into a drawable box, or `null` when it is unusable.
 *
 * Coordinates are backend pixels in the detection frame; they are clamped into
 * that frame and then expressed as a percentage of it, so the box tracks the
 * image element and never the browser window.
 */
export function toOverlayBox(
  d: Detection,
  frame: FrameSize,
  ctx: OverlayContext = {},
  index = 0,
): OverlayBox | null {
  if (!d) return null
  // A coordinate that is not a number is not a box that can be drawn. Clamping
  // it to 0 would invent a rectangle anchored at the frame corner.
  if (![d.x1, d.y1, d.x2, d.y2].every(isFiniteNumber)) return null
  if (!isFiniteNumber(d.confidence)) return null
  const x1 = clamp(d.x1, 0, frame.width)
  const y1 = clamp(d.y1, 0, frame.height)
  const x2 = clamp(d.x2, 0, frame.width)
  const y2 = clamp(d.y2, 0, frame.height)
  const w = x2 - x1
  const h = y2 - y1
  if (w < MIN_BOX_PX || h < MIN_BOX_PX) return null

  const isUnknown = d.class_name === UNKNOWN_CLASS
  const instanceId = d.instance_id ?? null
  const isUnattended =
    isUnknown && instanceId != null && ctx.unattendedIds?.has(instanceId) === true
  const risk = isUnknown ? null : ctx.hazardLevels?.[d.class_name] ?? null
  const isHazard = !isUnknown && risk != null && risk !== 'SAFE'
  const style: BoxStyle = isUnattended
    ? 'unattended'
    : isUnknown
      ? 'unknown'
      : isHazard
        ? 'hazard'
        : 'known'

  const left = (x1 / frame.width) * 100
  const top = (y1 / frame.height) * 100
  return {
    key: `${d.class_name}:${instanceId ?? index}:${d.x1},${d.y1}`,
    className: d.class_name,
    instanceId,
    style,
    color: BOX_COLORS[style],
    dashed: BOX_DASHED[style],
    text: labelFor(d, style, risk),
    confidence: d.confidence,
    left,
    top,
    width: (w / frame.width) * 100,
    height: (h / frame.height) * 100,
    labelAbove: top >= 5,
  }
}

function iou(a: OverlayBox, b: OverlayBox): number {
  const ix = Math.max(0, Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left))
  const iy = Math.max(0, Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top))
  const inter = ix * iy
  if (inter <= 0) return 0
  const union = a.width * a.height + b.width * b.height - inter
  return union > 0 ? inter / union : 0
}

function centresInside(a: OverlayBox, b: OverlayBox): boolean {
  const acx = a.left + a.width / 2
  const acy = a.top + a.height / 2
  const bcx = b.left + b.width / 2
  const bcy = b.top + b.height / 2
  const inB = acx >= b.left && acx <= b.left + b.width && acy >= b.top && acy <= b.top + b.height
  const inA = bcx >= a.left && bcx <= a.left + a.width && bcy >= a.top && bcy <= a.top + a.height
  return inB || inA
}

function isDuplicateOfKnown(box: OverlayBox, known: readonly OverlayBox[]): boolean {
  return known.some(k => iou(k, box) >= UNKNOWN_DUPLICATE_IOU || centresInside(k, box))
}

/**
 * Build the render list for one frame.
 *
 * Known and unknown detections stay separate feeds all the way from the
 * backend; they are combined here, for drawing only. Unknown boxes are emitted
 * first so the recognised boxes paint over them: a duplicate orange box must
 * never be the only thing the operator can see on a person.
 */
export function buildOverlay(
  detections: readonly Detection[] | null | undefined,
  unknownDetections: readonly Detection[] | null | undefined,
  frameWidth: number | null | undefined,
  frameHeight: number | null | undefined,
  ctx: OverlayContext = {},
): OverlayBox[] {
  const frame = resolveFrameSize(frameWidth, frameHeight)
  if (!frame) return []

  const known: OverlayBox[] = []
  detections?.forEach((d, i) => {
    const box = toOverlayBox(d, frame, ctx, i)
    if (box) known.push(box)
  })

  const unknown: OverlayBox[] = []
  unknownDetections?.forEach((d, i) => {
    const box = toOverlayBox(d, frame, ctx, i)
    if (!box) return
    if (isDuplicateOfKnown(box, known)) return
    unknown.push(box)
  })

  return [...unknown, ...known]
}

/**
 * class name -> risk level, read from the safety snapshot.
 *
 * The hazard vocabulary lives in the backend knowledge base (`hazards.json`);
 * duplicating it here would let the two disagree and the overlay would colour
 * an object the safety engine considers harmless.
 */
export function hazardLevelsFrom(
  assessments: readonly HazardAssessment[] | null | undefined,
): Record<string, RiskLevel> | null {
  if (!assessments || assessments.length === 0) return null
  const levels: Record<string, RiskLevel> = {}
  for (const a of assessments) {
    // Keep the worst rating when one class is seen more than once.
    const previous = levels[a.object]
    if (previous === undefined || previous === 'SAFE' || a.risk_level !== 'SAFE') {
      levels[a.object] = a.risk_level
    }
  }
  return levels
}

/**
 * Instance ids the attendance monitor has declared UNATTENDED. Matching on
 * `instance_id` is what ties the red dashed box to the same track the
 * attendance chain is talking about, instead of guessing from coordinates.
 */
export function unattendedIdsFrom(
  watches: readonly AttendanceWatch[] | null | undefined,
): Set<string> {
  const ids = new Set<string>()
  watches?.forEach(w => {
    if (w.state === 'UNATTENDED') ids.add(w.instanceId)
  })
  return ids
}

/** Per-class box colors used for the live-feed overlay. */
export const CLASS_COLOR: Record<string, string> = {
  person: '#34d399',
  knife: '#a78bfa',
  pen: '#38bdf8',
  red_box: '#f43f5e',
  yellow_box: '#fbbf24',
  floating_tool: '#fb923c',
  loose_cable: '#64748b',
  bottle: '#2dd4bf',
  unknown_object: BOX_COLORS.unknown,
}

export const DETECTION_STATUS_URL = '/api/detection/status'
export const DETECTIONS_URL = '/api/detections'
export const DETECTION_POLL_MS = 1000