import test from 'node:test'
import assert from 'node:assert/strict'
import { paintOf } from '../src/tableSpans.ts'

const table = (extra: object) => ({
  columns: [{ key: 'well' }, { key: 'pack' }, { key: 's0_kg' }, { key: 's0_abs' }], rows: [], count: 3, ...extra,
}) as never

test('заливка строки и синий шрифт; правило на колонки — только эти колонки', () => {
  const paint = paintOf(table({
    styles: [{ rows: [0, 1], fill: 'FCD5B4', font: '', columns: [] }, { rows: [1], fill: 'D3EBF7', font: '1F3FBF', columns: ['s0_kg'] }],
  }))
  assert.deepEqual(paint.cell.get('0:0'), { backgroundColor: '#FCD5B4' })
  assert.deepEqual(paint.cell.get('1:2'), { backgroundColor: '#D3EBF7', color: '#1F3FBF' })
  assert.deepEqual(paint.cell.get('1:3'), { backgroundColor: '#FCD5B4' })     // колонка без правила — только заливка строки
  assert.equal(paint.cell.get('2:0'), undefined)
})

test('объединение: левая верхняя ячейка с пролётами, остальные скрыты', () => {
  const paint = paintOf(table({ merges: [{ first: 0, last: 2, columns: ['s0_kg', 's0_abs'] }] }))
  assert.deepEqual(paint.starts.get('0:2'), { rowSpan: 3, colSpan: 2 })
  assert.deepEqual([...paint.covered].sort(), ['0:3', '1:2', '1:3', '2:2', '2:3'])
})

test('неизвестная колонка в правилах не ломает таблицу', () => {
  const paint = paintOf(table({ styles: [{ rows: [0], fill: 'FFFFFF', font: '', columns: ['нет'] }] }))
  assert.equal(paint.cell.size, 0)
})
