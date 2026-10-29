import test from 'node:test'
import assert from 'node:assert/strict'
import { applyLooks, looksOf, markerSymbol, seriesLookKey, yearOfKey } from '../src/chartStyle.ts'

const series = (name: string, kind: 'line' | 'points' = 'line', group = '') => ({ name, kind, group }) as never
const chart = { title: 'Расход', y: { label: 'Q' }, y2: null, x: {}, series: [series('ГСП-1'), series('ГСП-2', 'points')] } as never

test('ключ ряда — группа или имя и вид', () => {
  assert.equal(seriesLookKey(series('ГСП-1')), 'ГСП-1|line')
  assert.equal(seriesLookKey(series('Давление', 'points', 'ГСП-8')), 'ГСП-8|points')
})

test('вид берётся по ключам рядов графика, а не по его заголовку', () => {
  const all = { 'ГСП-2|points': { color: '#000000' }, 'ГСП-9|line': { color: '#111111' } }
  assert.deepEqual(looksOf(chart as never, all), { 'ГСП-2|points': { color: '#000000' } })
  const renamed = { ...(chart as object), title: 'Другой заголовок', series: [series('ГСП-2', 'points')] } as never
  assert.deepEqual(looksOf(renamed, all), { 'ГСП-2|points': { color: '#000000' } })
})

test('без личного вида график не меняется', () => {
  assert.equal(applyLooks(chart as never, undefined), chart)
  assert.equal(applyLooks(chart as never, {}), chart)
})

test('вид подставляется только к своему ряду', () => {
  const out = applyLooks(chart as never, { 'ГСП-2|points': { color: '#000000', size: 12 } })
  assert.equal(out.series[0], (chart as { series: unknown[] }).series[0])
  assert.deepEqual((out.series[1] as { look: unknown }).look, { color: '#000000', size: 12 })
})

test('форма без выбора — из модуля, с выбором — из набора', () => {
  assert.equal(markerSymbol(undefined, 'rect'), 'rect')
  assert.equal(markerSymbol('square', 'circle'), 'rect')
  assert.ok(markerSymbol('star', 'circle').startsWith('path://'))
  assert.ok(markerSymbol('plus', 'circle').startsWith('path://'))
  assert.ok(markerSymbol('x', 'circle').startsWith('path://'))
})

test('год узнаётся в ключе ряда: год, сезон, без года', () => {
  assert.equal(yearOfKey('2024|bar'), 2024)
  assert.equal(yearOfKey('2023/2024|line'), 2023)
  assert.equal(yearOfKey('Сезон 2022|bar'), 2022)
  assert.equal(yearOfKey('ГСП 12|line'), null)
  assert.equal(yearOfKey('№ 1204|points'), null)
})
