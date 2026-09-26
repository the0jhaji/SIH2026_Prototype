/**
 * Direct test of the live-feed detection overlay
 * (frontend/src/domain/detection.ts).
 * Runs on Node's native TypeScript type-stripping (Node 22.18+/23+).
 *
 *   npm run test:overlay
 *
 * Covers the contract the dashboard depends on: backend pixel coordinates in a
 * known frame size must become clamped percentages of that frame, unknown
 * proposals must be drawn (orange, dashed) with their instance id, unattended
 * ones must turn red dashed, and no invalid box may reach the DOM.
 */

import {
  BOX_COLORS,
  buildOverlay,
  hazardLevelsFrom,
  resolveFrameSize,
  unattendedIdsFrom,
} from '../src/domain/detection.ts'

let failures = 0

function check(name, condition, detail = '') {
  if (condition) {
    console.log(`  ok   ${name}`)
  } else {
    failures += 1
    console.error(`  FAIL ${name}${detail ? ` -- ${detail}` : ''}`)
  }
}

function near(a, b, epsilon = 1e-6) {
  return Math.abs(a - b) <= epsilon
}

const TS = 1_700_000_000_000

function det(class_name, x1, y1, x2, y2, extra = {}) {
  return { class_name, confidence: 0.5, x1, y1, x2, y2, timestamp: TS, ...extra }
}

function unknownDet(x1, y1, x2, y2, id) {
  return det('unknown_object', x1, y1, x2, y2, { confidence: 0.6103, instance_id: id })
}

console.log('frame resolution')
check('rejects null', resolveFrameSize(null, 720) === null)
check('rejects zero', resolveFrameSize(1280, 0) === null)
check('rejects negative', resolveFrameSize(-1, 720) === null)
check('rejects NaN', resolveFrameSize(NaN, 720) === null)
check('accepts 1280x720', JSON.stringify(resolveFrameSize(1280, 720)) === '{"width":1280,"height":720}')

console.log('\n1280x720 pixel -> percent mapping')
{
  // The exact payload shape reported by the backend.
  const boxes = buildOverlay(
    [det('person', 381, 329, 881, 713, { confidence: 0.9275 })],
    [unknownDet(260, 3, 431, 173, 'unknown-100'), unknownDet(264, 577, 443, 720, 'unknown-106')],
    1280,
    720,
  )
  check('three boxes drawn', boxes.length === 3, `got ${boxes.length}`)

  const person = boxes.find(b => b.className === 'person')
  check('person is green', person?.color === BOX_COLORS.known)
  check('person is solid', person?.dashed === false)
  check('person left', near(person?.left, (381 / 1280) * 100))
  check('person top', near(person?.top, (329 / 720) * 100))
  check('person width', near(person?.width, (500 / 1280) * 100))
  check('person height', near(person?.height, (384 / 720) * 100))

  const u1 = boxes.find(b => b.instanceId === 'unknown-100')
  check('unknown-100 drawn', u1 !== undefined)
  check('unknown is orange', u1?.color === BOX_COLORS.unknown, u1?.color)
  check('unknown is dashed', u1?.dashed === true)
  check('unknown label', u1?.text === 'UNKNOWN OBJECT • 61% • unknown-100', u1?.text)
  check('unknown top clamped to 0', near(u1?.top, (3 / 720) * 100))
  check('unknown hugs top -> label inside', u1?.labelAbove === false)

  const u2 = boxes.find(b => b.instanceId === 'unknown-106')
  check('unknown-106 drawn', u2 !== undefined)
  check('unknown-106 bottom is frame bottom', near((u2?.top ?? 0) + (u2?.height ?? 0), 100))
  check('unknown-106 label above', u2?.labelAbove === true)
}

console.log('\nother frame sizes')
for (const [w, h] of [
  [1920, 1080],
  [640, 640],
  [640, 480],
  [320, 240],
]) {
  const boxes = buildOverlay([det('person', 0, 0, w / 2, h / 2)], [], w, h)
  const person = boxes[0]
  check(
    `${w}x${h} full-half box maps to 50%/50%`,
    near(person?.left, 0) &&
      near(person?.top, 0) &&
      near(person?.width, 50) &&
      near(person?.height, 50),
    `got ${person?.left},${person?.top},${person?.width},${person?.height}`,
  )
}

console.log('\nclamping and rejection')
{
  const boxes = buildOverlay(
    [
      det('person', -50, -20, 5000, 5000),
      det('bottle', 100, 100, 100, 100), // degenerate
      det('cup', 'x', 10, 20, 30), // malformed
    ],
    [],
    1280,
    720,
  )
  const person = boxes.find(b => b.className === 'person')
  check('oversized box clamped to frame', person?.left === 0 && person?.top === 0)
  check('oversized box width is 100%', near(person?.width, 100) && near(person?.height, 100))
  check('degenerate box dropped', !boxes.some(b => b.className === 'bottle'))
  check('malformed box dropped', !boxes.some(b => b.className === 'cup'))

  const u = buildOverlay([], [unknownDet(-10, -10, 99999, 99999, 'unknown-x')], 1280, 720)
  check('oversized unknown clamped', near(u[0]?.width, 100) && near(u[0]?.height, 100))
  check(
    'every box is inside 0..100',
    [...boxes, ...u].every(
      b => b.left >= 0 && b.top >= 0 && b.left + b.width <= 100 + 1e-9 && b.top + b.height <= 100 + 1e-9,
    ),
  )
}

console.log('\nno frame -> nothing drawn')
{
  check('null frame yields no boxes', buildOverlay([det('person', 0, 0, 10, 10)], [], null, null).length === 0)
  check('zero frame yields no boxes', buildOverlay([det('person', 0, 0, 10, 10)], [], 0, 0).length === 0)
}

console.log('\nstyle / colour classification')
{
  const hazardLevels = hazardLevelsFrom([
    { object: 'knife', risk_level: 'CRITICAL' },
    { object: 'bottle', risk_level: 'SAFE' },
    { object: 'person', risk_level: 'SAFE' },
  ])
  const boxes = buildOverlay(
    [det('knife', 10, 10, 100, 100), det('bottle', 200, 200, 300, 300), det('person', 400, 400, 500, 500)],
    [unknownDet(600, 600, 700, 700, 'unknown-1')],
    1280,
    720,
    { hazardLevels },
  )
  const knife = boxes.find(b => b.className === 'knife')
  check('hazard class is red', knife?.color === BOX_COLORS.hazard)
  check('hazard class is solid', knife?.dashed === false)
  check('hazard label carries the level', knife?.text === 'KNIFE • 50% • CRITICAL', knife?.text)
  const bottle = boxes.find(b => b.className === 'bottle')
  check('SAFE-rated known class stays green', bottle?.color === BOX_COLORS.known)
  check('person stays green', boxes.find(b => b.className === 'person')?.color === BOX_COLORS.known)
}

console.log('\nunattended unknown objects')
{
  const watches = [
    { instanceId: 'unknown-7', state: 'UNATTENDED', isUnknown: true },
    { instanceId: 'unknown-8', state: 'HELD', isUnknown: true },
  ]
  const unattendedIds = unattendedIdsFrom(watches)
  check('only UNATTENDED collected', unattendedIds.size === 1 && unattendedIds.has('unknown-7'))
  const boxes = buildOverlay(
    [],
    [unknownDet(10, 10, 200, 200, 'unknown-7'), unknownDet(300, 10, 500, 200, 'unknown-8')],
    1280,
    720,
    { unattendedIds },
  )
  const attended = boxes.find(b => b.instanceId === 'unknown-7')
  const held = boxes.find(b => b.instanceId === 'unknown-8')
  check('unattended is red', attended?.color === BOX_COLORS.unattended)
  check('unattended is dashed', attended?.dashed === true)
  check(
    'unattended label',
    attended?.text === 'UNATTENDED OBJECT • 61% • unknown-7',
    attended?.text,
  )
  check('non-unattended unknown stays orange', held?.color === BOX_COLORS.unknown)
}

console.log('\nvisual priority')
{
  // A known person box and an unknown proposal on the same pixels: the
  // proposal is a duplicate report and must not be drawn over the person.
  const boxes = buildOverlay(
    [det('person', 100, 100, 400, 400)],
    [unknownDet(110, 110, 390, 390, 'unknown-dup')],
    1280,
    720,
  )
  check('duplicate unknown dropped', boxes.length === 1)
  check('known box survives', boxes[0]?.className === 'person')

  // Disjoint boxes: both drawn, unknown first so known paints on top.
  const both = buildOverlay(
    [det('person', 0, 0, 300, 300)],
    [unknownDet(900, 500, 1100, 700, 'unknown-far')],
    1280,
    720,
  )
  check('disjoint unknown kept', both.length === 2)
  check('unknown emitted before known', both[0]?.className === 'unknown_object' && both[1]?.className === 'person')

  // The real 1280x720 pair: a motion blob overlapping the lower-left corner of
  // a large person box is a DIFFERENT region of the frame, not a duplicate.
  // A containment-style metric drops it and silently loses a real unknown.
  const partial = buildOverlay(
    [det('person', 381, 329, 881, 713)],
    [unknownDet(264, 577, 443, 720, 'unknown-106')],
    1280,
    720,
  )
  check('partially overlapping unknown kept', partial.length === 2, `got ${partial.length}`)
  check('partially overlapping unknown still unknown', partial.some(b => b.instanceId === 'unknown-106'))
}

console.log('\nspeculative open-vocabulary label')
{
  const boxes = buildOverlay(
    [],
    [det('unknown_object', 10, 10, 200, 200, { confidence: 0.78, instance_id: 'unknown-9', possible_label: 'bottle' })],
    1280,
    720,
  )
  check('possible label is not a claim', boxes[0]?.text === 'POSSIBLE BOTTLE • 78% • unknown-9', boxes[0]?.text)
  check('possible label keeps the unknown colour', boxes[0]?.color === BOX_COLORS.unknown)
  check('possible label stays dashed', boxes[0]?.dashed === true)
}

console.log('')
if (failures > 0) {
  console.error(`FAIL — ${failures} check(s) failed`)
  process.exit(1)
}
console.log('PASS')
