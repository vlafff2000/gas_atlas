import test from 'node:test'
import assert from 'node:assert/strict'
import { placeTip, coveredCount, type Track, type View } from '../src/chartHover.ts'

const view: View = { toPixel: (x, y) => [x, y], fromPixel: (px, py) => [px, py], visible: () => true }
function cloud(pts: Array<[number, number]>): Track {
  const xs = Float64Array.from(pts.map(p => p[0])), ys = Float64Array.from(pts.map(p => p[1]))
  return { index: 0, series: {} as never, axis: 0, xs, ys, src: Uint32Array.from(pts.map((_, i) => i)), monotonic: true,
    curve: false, points: true, bar: false, order: null }
}
const bounds = { x: 0, y: 0, w: 600, h: 300 }

test('карточка не лежит на точках, если есть свободное место', () => {
  const dots: Array<[number, number]> = []
  for (let x = 320; x < 480; x += 8) for (let y = 100; y < 200; y += 8) dots.push([x, y])   // облако справа от курсора
  const t = cloud(dots)
  const [x, y] = placeTip([t], view, [300, 150], [140, 80], bounds)
  assert.equal(coveredCount([t], view, { x, y, w: 140, h: 80 }), 0)
})

test('карточка не накрывает точку наведения', () => {
  const [x, y] = placeTip([], view, [590, 150], [140, 80], bounds)
  assert.ok(!(590 >= x && 590 <= x + 140 && 150 >= y && 150 <= y + 80))
})
