import assert from 'node:assert/strict'
import test from 'node:test'
import { dragTarget, elementAt, elementTitle, formatTarget, isShifted, movable, shifted, unshifted, withFix, withPlace, withSkip, type SceneElement } from '../src/exportStageLogic.ts'

const el = (id: string, kind: string, box: [number, number, number, number], extra: Partial<SceneElement> = {}): SceneElement => ({ id, kind, box, ...extra })
const scene: SceneElement[] = [
  el('plot', 'plot', [0.1, 0.1, 0.9, 0.85]),
  el('title', 'title', [0.1, 0.01, 0.4, 0.05], { text: 'Проба' }),
  el('series:пласт', 'series', [0.2, 0.2, 0.8, 0.8], { series: 'пласт', axis: 'y2' }),
  el('label:пласт:2024-03-01', 'label', [0.5, 0.3, 0.52, 0.33], { series: 'пласт', point: '2024-03-01', text: '97' }),
  el('legend', 'legend', [0.3, 0.92, 0.7, 0.98]),
  el('legend:пласт', 'legend-item', [0.32, 0.93, 0.45, 0.97], { text: 'пласт' }),
]

test('под точкой — самый маленький элемент; поле построения уступает всем', () => {
  assert.equal(elementAt(scene, 0.51, 0.31)?.id, 'label:пласт:2024-03-01')
  assert.equal(elementAt(scene, 0.3, 0.5)?.id, 'series:пласт')
  assert.equal(elementAt(scene, 0.15, 0.15)?.id, 'plot')
  assert.equal(elementAt(scene, 0.35, 0.95)?.id, 'legend:пласт')
  assert.equal(elementAt(scene, 0.6, 0.95)?.id, 'legend')
  assert.equal(elementAt(scene, 0.99, 0.99), null)
})

test('запас вокруг рамки помогает попасть в мелкую подпись', () => {
  assert.equal(elementAt(scene, 0.525, 0.335)?.id, 'series:пласт')
  assert.equal(elementAt(scene, 0.525, 0.335, [0.01, 0.01])?.id, 'label:пласт:2024-03-01')
})

test('сдвиг копится, округляется и не хранит ноль', () => {
  let doc = shifted({ chart: { title_size: 14 } }, 'title', 0.1, -0.05)
  assert.deepEqual(doc, { chart: { title_size: 14 }, elements: { title: { dx: 0.1, dy: -0.05 } } })
  doc = shifted(doc, 'title', 0.02345678, 0.05)
  assert.deepEqual(doc.elements, { title: { dx: 0.1235 } })
  assert.ok(isShifted(doc, 'title') && !isShifted(doc, 'legend'))
  assert.deepEqual(unshifted(doc, 'title'), { chart: { title_size: 14 } })
  assert.deepEqual(shifted({}, 'legend', 5, -5).elements, { legend: { dx: 1, dy: -1 } })
})

test('спрятанная подпись остаётся спрятанной после сброса положения', () => {
  let doc = withPlace({}, 'label:пласт:2024-03-01', { hide: true })
  doc = shifted(doc, 'label:пласт:2024-03-01', 0.01, 0)
  assert.deepEqual(unshifted(doc, 'label:пласт:2024-03-01').elements, { 'label:пласт:2024-03-01': { hide: true } })
  assert.deepEqual(withPlace(doc, 'label:пласт:2024-03-01', { hide: false }).elements, { 'label:пласт:2024-03-01': { dx: 0.01 } })
  assert.deepEqual(withPlace(doc, 'label:пласт:2024-03-01', null), {})
})

test('двигать можно заголовок, легенду, подписи; ряд, ось и спрятанное — нельзя', () => {
  assert.ok(movable(scene[1]) && movable(scene[3]) && movable(scene[4]))
  assert.ok(!movable(scene[0]) && !movable(scene[2]) && !movable(scene[5]) && !movable(null))
  assert.ok(!movable({ ...scene[3], hidden: true }))
})

test('названия элементов понятны инженеру', () => {
  assert.equal(elementTitle(scene[1]), 'Заголовок «Проба»')
  assert.equal(elementTitle(scene[3]), 'Подпись «97»: ряд «пласт», 01.03.2024')
  assert.equal(elementTitle(el('axis-title:y2', 'axis-title', [0, 0, 1, 1], { axis: 'y2', text: 'Давление' })), 'Название оси Y2 «Давление»')
  assert.equal(elementTitle(el('axis:x', 'axis', [0, 0, 1, 1], { axis: 'x' })), 'Ось X')
})

test('двойной щелчок открывает нужный раздел панели «Формат»', () => {
  const names = ['расход', 'пласт', 'пласт']
  assert.equal(formatTarget(scene[1], names), 'chart')
  assert.equal(formatTarget(scene[2], names), 'series:1')
  assert.equal(formatTarget(el('series:пласт#2', 'series', [0, 0, 1, 1], { series: 'пласт#2' }), names), 'series:2')
  assert.equal(formatTarget(scene[5], names), 'series:1')
  assert.equal(formatTarget(el('axis-title:y2', 'axis-title', [0, 0, 1, 1], { axis: 'y2' }), names), 'axis:y2')
  assert.equal(formatTarget(el('series:нет', 'series', [0, 0, 1, 1], { series: 'нет' }), names), 'chart')
})

test('за пункт легенды тянется вся легенда; ряд и ось не тянутся', () => {
  assert.equal(dragTarget(scene, scene[5])?.id, 'legend')
  assert.equal(dragTarget(scene, scene[1])?.id, 'title')
  assert.equal(dragTarget(scene, scene[2]), null)
  assert.equal(dragTarget(scene, null), null)
  assert.equal(dragTarget(scene, { ...scene[3], hidden: true }), null)
})

test('снятая находка проверки качества хранится в оформлении графика и возвращается', () => {
  const moved = withPlace({}, 'title', { dx: 0.1 })
  let doc = withSkip(moved, 'overlap:legend|title', true)
  doc = withSkip(doc, 'overlap:legend|title', true)      // повторное снятие не дублирует ключ
  doc = withSkip(doc, 'small-font', true)
  assert.deepEqual(doc, { elements: { title: { dx: 0.1 } }, checks: { skip: ['overlap:legend|title', 'small-font'] } })
  assert.deepEqual(withSkip(doc, 'overlap:legend|title', false).checks, { skip: ['small-font'] })
  assert.deepEqual(withSkip(withSkip(doc, 'overlap:legend|title', false), 'small-font', false), moved)      // пустого раздела не остаётся
})

test('исправление находки меняет положение нескольких элементов разом', () => {
  let doc = withPlace(withPlace({}, 'legend', { dx: -0.3, dy: -0.9 }), 'title', { dx: 0.1 })
  doc = withFix(doc, { text: 'x', places: { legend: null, 'label:а:1': { hide: true }, 'label:а:2': { hide: true } } })
  assert.deepEqual(doc, { elements: { title: { dx: 0.1 }, 'label:а:1': { hide: true }, 'label:а:2': { hide: true } } })
  assert.deepEqual(withFix({}, { text: 'x', places: { legend: null } }), {})
})
