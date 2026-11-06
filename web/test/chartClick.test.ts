import test from 'node:test'
import assert from 'node:assert/strict'
import { hover, type Track, type View } from '../src/chartHover.ts'
import { clickAction } from '../src/chartClick.ts'

const view: View = { toPixel: (x, y) => [x, y], fromPixel: (px, py) => [px, py], visible: () => true }
function marks(series: object, pts: Array<[number, number]>, index: number): Track {
  return { index, series: series as never, axis: 0, xs: Float64Array.from(pts.map(p => p[0])), ys: Float64Array.from(pts.map(p => p[1])),
    src: Uint32Array.from(pts.map((_, i) => i)), monotonic: true, curve: true, points: true, bar: false, step: false, order: null }
}
const mean = marks({ name: 'Пластовое давление объекта', markers: true }, [[100, 100]], 0)            // расчётная кривая: ни ids, ни dataset
const measured = marks({ name: 'Давление (пересчет)', markers: true, ids: ['a'], dataset: 'response' }, [[103, 100]], 1)

test('в режиме исключения точка с ids важнее соседней расчётной отметки', () => {
  assert.equal(hover([mean, measured], view, 100, 100, 'linear', () => 'linear', 'smooth').point?.track, mean)   // без режима: ближайшая
  assert.equal(hover([mean, measured], view, 100, 100, 'linear', () => 'linear', 'smooth', true).point?.track, measured)
})

const base = { moved: false, hover: true, boxActive: false, labelPicker: false, excludeMode: true }

test('щелчок по замеру в режиме исключения исключает, а не закрепляет подсказку', () => {
  assert.equal(clickAction({ ...base, point: { excludable: true, suspect: false, valueLabels: false } }), 'exclude')
  assert.equal(clickAction({ ...base, point: { excludable: true, suspect: true, valueLabels: false } }), 'suspect')
})

test('щелчок по расчётной отметке в режиме исключения не закрепляет подсказку, а объясняет', () => {
  assert.equal(clickAction({ ...base, point: { excludable: false, suspect: false, valueLabels: false } }), 'not-excludable')
})

test('без режима исключения щелчок закрепляет подсказку; перетаскивание ничего не делает', () => {
  assert.equal(clickAction({ ...base, excludeMode: false, point: { excludable: true, suspect: false, valueLabels: false } }), 'pin')
  assert.equal(clickAction({ ...base, excludeMode: true, point: null }), 'pin')
  assert.equal(clickAction({ ...base, moved: true, point: null }), 'none')
  assert.equal(clickAction({ ...base, boxActive: true, point: null }), 'none')
})

test('выбор подписей данных важнее исключения', () => {
  assert.equal(clickAction({ ...base, labelPicker: true, point: { excludable: true, suspect: false, valueLabels: true } }), 'label')
})
