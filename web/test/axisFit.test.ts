import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { boundText, clean, extentOf, fitAxes, fitChart, fitHint, isNice, niceStep, outlierText, unfitted, WHY, type Need } from '../src/axisFit.ts'

// Та же таблица, что проверяет atlas/axis_fit.py (tests/test_axis_fit.py): экран и файл обязаны давать одни числа.
const cases: { name: string; needs: (Need | null)[]; expect: ({ min: number; max: number; step: number; n: number | null; why: string } | null)[] }[] =
  JSON.parse(readFileSync(new URL('../../tests/fixtures/axis_fit_cases.json', import.meta.url), 'utf-8'))

for (const c of cases) {
  test(`таблица: ${c.name}`, () => {
    const got = fitAxes(c.needs).map(f => f && { min: f.minimum, max: f.maximum, step: f.step, n: f.n, why: f.why })
    assert.deepEqual(got, c.expect)
  })
}

test('случайная сверочная таблица: те же числа, что у atlas/axis_fit.py', () => {
  const random: { needs: (Need | null)[]; expect: ([number, number, number, number | null, string] | null)[] }[] =
    JSON.parse(readFileSync(new URL('../../tests/fixtures/axis_fit_random.json', import.meta.url), 'utf-8'))
  assert.equal(random.length, 360)        // 300 наборов шкал Y и 60 осей X
  for (const c of random) {
    const got = fitAxes(c.needs).map(f => f && [f.minimum, f.maximum, f.step, f.n, f.why])
    assert.deepEqual(got, c.expect, JSON.stringify(c.needs))
  }
})

test('у каждой причины есть текст', () => {
  for (const c of cases) for (const e of c.expect) if (e) assert.ok(WHY[e.why], e.why)
})

test('круглый шаг и число без двоичного хвоста', () => {
  assert.deepEqual([0.11, 1, 1.2, 2.4, 2.6, 7, 523].map(niceStep), [0.2, 1, 2, 2.5, 5, 10, 1000])
  assert.ok(isNice(0.25) && isNice(5000) && !isNice(14) && !isNice(0))
  assert.equal(clean(98.60000000000001), 98.6)
  assert.equal(clean(0.1 + 0.2), 0.3)
})

// --- график целиком (зеркало atlas/axis_auto.py) ---

const axis = (extra: object = {}) => ({ label: 'Давление', unit: 'кгс/см²', scale: 'value', inverse: false, from_zero: false, step: null, categories: null,
  minimum: null, maximum: null, style: {}, ...extra })
const line = (y: (number | null)[], extra: object = {}) => ({ name: 's', kind: 'line', x: y.map((_v, i) => i), y, axis: 'y', ...extra })
const chart = (series: object[], extra: object = {}) => ({ id: 'c', title: 'T', x: { scale: 'time' }, y: axis(), y2: null, y3: null, y4: null, y5: null, series, ...extra }) as never
const bounds = (a: { minimum: number | null; maximum: number | null; step: number | null }) => [a.minimum, a.maximum, a.step]

test('график: подбор как на сервере, повторный подбор ничего не меняет', () => {
  const once = fitChart(chart([line([44.3, 60, 87.2])]))
  assert.deepEqual(bounds(once.y), [40, 90, 10])
  assert.deepEqual(once.y.auto, { n: 5, zero: false, why: 'cut', lo: 44.3, hi: 87.2, anchor: false, min: 40, max: 90, step: 10 })
  assert.equal(fitChart(once), once)
})

test('график: «с нуля», режим и ручная граница пересчитывают подобранное, ручное остаётся', () => {
  const once = fitChart(chart([line([44.3, 60, 87.2])]))
  assert.deepEqual(bounds(fitChart({ ...once, y: { ...once.y, from_zero: true } }).y), [0, 100, 20])
  assert.deepEqual(bounds(fitChart({ ...once, y: { ...once.y, style: { fit: 'zero' } } }).y), [0, 100, 20])
  assert.deepEqual(bounds(fitChart({ ...once, y: { ...once.y, from_zero: true, style: { fit: 'auto' } } }).y), [40, 90, 10])      // режим из оформления главнее признака раздела
  const manual = fitChart({ ...once, y: { ...once.y, minimum: 0 } })
  assert.deepEqual(bounds(manual.y), [0, 100, 20])
  assert.equal(manual.y.auto?.min, undefined)                 // минимум ручной: в подобранном не числится
  const both = fitChart({ ...once, y: { ...once.y, minimum: 50, maximum: 80 } })
  assert.deepEqual([both.y.minimum, both.y.maximum, both.y.step, both.y.auto], [50, 80, null, null])
})

test('график: столбцы от нуля, стопка по сумме, ящики не трогаем', () => {
  assert.deepEqual(bounds(fitChart(chart([line([41, 100.5], { kind: 'bar' })])).y), [0, 120, 20])
  const stack = chart([line([40, 10], { kind: 'bar', stack: 'k' }), line([30, 10], { kind: 'bar', stack: 'k' }), line([-5, null], { kind: 'bar', stack: 'k' })])
  assert.deepEqual(extentOf(stack, 'y'), { lo: -5, hi: 70, anchor: true })
  const boxed = chart([line([1, 2], { kind: 'box' })])
  assert.equal(fitChart(boxed), boxed)
})

test('график: размах с сервера (полные данные) не теряется при прореженных рядах, ряды тренда его расширяют', () => {
  const server = fitChart(chart([line([44.3, 60, 87.2])]))
  const thinned = { ...server, series: [line([50, 60, 70])] } as never
  assert.deepEqual(bounds(fitChart(thinned).y), [40, 90, 10])
  const trend = { ...server, series: [line([44.3, 60, 87.2]), line([40, 130])] } as never
  assert.deepEqual(bounds(fitChart(trend).y), [20, 140, 20])
})

test('график: шкала стала логарифмической — подобранное снимается', () => {
  const once = fitChart(chart([line([44.3, 60, 87.2])]))
  const log = fitChart({ ...once, y: { ...once.y, scale: 'log' } })
  assert.deepEqual([log.y.minimum, log.y.maximum, log.y.step, log.y.auto], [null, null, null, null])
  assert.deepEqual(bounds(unfitted(once.y)), [null, null, null])
  assert.ok(unfitted(once.y).auto)
})

test('график: все шкалы с одним числом делений', () => {
  const c = chart([line([44.3, 87.2]), line([300, 900], { axis: 'y2' }), line([150, 5000], { axis: 'y3' })], { y2: axis({ inverse: true }), y3: axis() })
  const out = fitChart(c)
  const counts = [out.y, out.y2!, out.y3!].map(a => Math.round((a.maximum! - a.minimum!) / a.step!))
  assert.equal(new Set(counts).size, 1)
  assert.equal(counts[0], out.y.auto?.n)
})

test('подсказки: почему такие пределы и выброс', () => {
  const once = fitChart(chart([line([44.3, 60, 87.2])]))
  assert.equal(fitHint(once.y), 'Сейчас: 40…90, шаг 10, делений 5 (одно число на все шкалы графика). Данные: 44,3…87,2. Причина: данные далеко от нуля — шкала срезана, чтобы кривая занимала поле.')
  assert.match(fitHint({ ...once.y, auto: { ...once.y.auto!, lo: 583.30636, hi: 1085.58013 } }), /Данные: 583,3…1086\./)
  assert.equal(fitHint(axis({ minimum: 0, maximum: 150 }) as never), 'Пределы заданы вручную или разделом: автоподбор их не меняет.')
  assert.equal(fitHint(axis() as never), '')
  assert.equal(outlierText({ kind: 'outlier', count: 1, values: [5000], share: 0.004, min: 45, max: 70 }), 'Выброс: значение 5000 — остальные данные занимают 1 % высоты поля. Ничего не отброшено.')
  assert.equal(boundText(98.60000000000001), '98,6')
})

test('ось X: числовая подбирается сама по себе, столбцы и даты не трогаются', () => {
  const xy = (xs: number[], extra: object = {}) => ({ name: 's', kind: 'line', x: xs, y: xs.map((_v, i) => i + 1), axis: 'y', ...extra })
  const once = fitChart(chart([xy([1, 50, 150])], { x: axis({ label: 'Сутки' }) }))
  assert.deepEqual(bounds(once.x), [0, 150, 25])
  assert.deepEqual(once.x.auto, { n: 6, zero: true, why: 'near', lo: 1, hi: 150, anchor: false, min: 0, max: 150, step: 25 })
  assert.equal(fitChart(once), once)
  assert.deepEqual(bounds(fitChart(chart([xy([100, 150, 200])], { x: axis() })).x), [100, 200, 20])      // без запаса у среза
  assert.deepEqual(bounds(fitChart(chart([xy([1, 2, 3], { kind: 'bar' })], { x: axis() })).x), [null, null, null])
  assert.deepEqual(bounds(fitChart({ ...once, x: { ...once.x, minimum: 10 } }).x), [10, 150, 20])           // ручной минимум сильнее
  assert.deepEqual(bounds(fitChart({ ...once, x: { ...unfitted(once.x), scale: 'log' } }).x), [null, null, null])      // лог. шкала: подобранное снимается
  assert.equal(fitHint(once.x, true), 'Сейчас: 0…150, шаг 25, делений 6. Данные: 1…150. Причина: нуль рядом с данными — шкала начата от нуля.')
})
