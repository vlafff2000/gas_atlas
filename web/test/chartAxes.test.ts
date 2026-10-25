import test from 'node:test'
import assert from 'node:assert/strict'
import { calendarTicks, fitAxisName, parseStep } from '../src/chartAxes.ts'

test('короткое название с единицами: название и единицы отдельной строкой', () => {
  const n = fitAxisName('Рпл', 'кгс/см²', 56, 12)
  assert.equal(n.text, 'Рпл\nкгс/см²')
  assert.equal(n.cut, false)
})

test('длинное название переносится, режется «…», единицы остаются целиком', () => {
  const n = fitAxisName('Суточный расход газа, накопленное (с начала периода)', 'млн м³', 56, 12)
  const lines = n.text.split('\n')
  assert.equal(n.cut, true)
  assert.equal(lines.length, 4)
  assert.ok(lines[2].endsWith('…'))
  assert.equal(lines[3], 'млн м³')
})

test('слишком длинное слово режется по ширине', () => {
  const n = fitAxisName('Сверхдлинноеназвание', '', 56, 12)
  assert.ok(n.text.split('\n').every(l => l.length <= 8))
})

test('parseStep: пусто — авто, дробь допустима у чисел, у дат только целое', () => {
  assert.equal(parseStep('', 'num'), null)
  assert.deepEqual(parseStep('2,5', 'num'), { n: 2.5, unit: 'num' })
  assert.equal(parseStep('1,5', 'month'), 'bad')
  assert.equal(parseStep('0', 'day'), 'bad')
  assert.deepEqual(parseStep('6', 'month'), { n: 6, unit: 'month' })
})

test('calendarTicks: месяцы с 1-го числа, годы с 1 января, недели с понедельника', () => {
  const d = (s: string) => Date.parse(s + 'T00:00:00Z')
  const iso = (a: number[]) => a.map(t => new Date(t).toISOString().slice(0, 10))
  assert.deepEqual(iso(calendarTicks(d('2024-02-10'), d('2025-01-05'), { n: 6, unit: 'month' })), ['2024-07-01', '2025-01-01'])
  assert.deepEqual(iso(calendarTicks(d('2023-05-01'), d('2026-01-01'), { n: 1, unit: 'year' })), ['2024-01-01', '2025-01-01', '2026-01-01'])
  assert.deepEqual(iso(calendarTicks(d('2024-05-15'), d('2024-06-01'), { n: 1, unit: 'week' })), ['2024-05-20', '2024-05-27'])
  assert.deepEqual(iso(calendarTicks(d('2024-01-01'), d('2024-01-10'), { n: 3, unit: 'day' })).length, 3)
})
