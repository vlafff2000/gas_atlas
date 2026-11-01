import { test } from 'node:test'
import assert from 'node:assert/strict'
import { marksAfterArrow, marksAfterNavigate, marksAfterSpace } from '../src/pickerSelection.ts'

const items = [{ name: 'sub', dir: true }, { name: 'a.xlsx', dir: false }, { name: 'b.xlsx', dir: false }]
const none = { marked: [], auto: [] }

test('стрелка на файл переносит автогалочку с прошлого файла на текущий', () => {
  const m1 = marksAfterArrow(items, 1, none)
  assert.deepEqual(m1, { marked: ['a.xlsx'], auto: ['a.xlsx'] })
  assert.deepEqual(marksAfterArrow(items, 2, m1), { marked: ['b.xlsx'], auto: ['b.xlsx'] })
})

test('стрелка на папку снимает автогалочку', () => {
  const m = marksAfterArrow(items, 0, { marked: ['b.xlsx'], auto: ['b.xlsx'] })
  assert.deepEqual(m, { marked: [], auto: [] })
})

test('ручная галочка переживает движение стрелками', () => {
  const manual = { marked: ['a.xlsx'], auto: [] }
  assert.deepEqual(marksAfterArrow(items, 0, manual), { marked: ['a.xlsx'], auto: [] })
  assert.deepEqual(marksAfterArrow(items, 2, manual), { marked: ['a.xlsx', 'b.xlsx'], auto: ['b.xlsx'] })
})

test('пробел на автогалочке делает её ручной, на пустой строке ставит, на ручной снимает', () => {
  assert.deepEqual(marksAfterSpace('a.xlsx', { marked: ['a.xlsx'], auto: ['a.xlsx'] }), { marked: ['a.xlsx'], auto: [] })
  assert.deepEqual(marksAfterSpace('b.xlsx', none), { marked: ['b.xlsx'], auto: [] })
  assert.deepEqual(marksAfterSpace('b.xlsx', { marked: ['b.xlsx'], auto: [] }), { marked: [], auto: [] })
})

test('смена папки: автогалочка пропадает, ручная переезжает с путём и возвращается при возврате', () => {
  const out = marksAfterNavigate({ marked: ['a.xlsx', 'b.xlsx'], auto: ['b.xlsx'] }, [], '/d', '/d/sub')
  assert.deepEqual(out, { marked: [], auto: [], carried: [{ dir: '/d', name: 'a.xlsx' }] })
  const back = marksAfterNavigate({ marked: out.marked, auto: out.auto }, out.carried, '/d/sub', '/d')
  assert.deepEqual(back, { marked: ['a.xlsx'], auto: [], carried: [] })
})

test('обновление той же папки ничего не меняет', () => {
  assert.deepEqual(marksAfterNavigate({ marked: ['a.xlsx'], auto: ['a.xlsx'] }, [], '/d', '/d'), { marked: ['a.xlsx'], auto: ['a.xlsx'], carried: [] })
})
