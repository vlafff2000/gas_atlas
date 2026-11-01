import { test } from 'node:test'
import assert from 'node:assert/strict'
import { marksAfterArrow, marksAfterNavigate } from '../src/pickerSelection.ts'

const items = [{ name: 'sub', dir: true }, { name: 'a.xlsx', dir: false }, { name: 'b.xlsx', dir: false }]

test('стрелка на файл переносит галочку на него', () => {
  assert.deepEqual(marksAfterArrow(items, 1, []), ['a.xlsx'])
  assert.deepEqual(marksAfterArrow(items, 2, ['a.xlsx']), ['b.xlsx'])
})

test('стрелка на папку снимает галочку с прошлого файла', () => {
  assert.deepEqual(marksAfterArrow(items, 0, ['b.xlsx']), [])
})

test('смена папки сбрасывает выбор, обновление той же папки — нет', () => {
  assert.deepEqual(marksAfterNavigate(['a.xlsx'], '/d', '/d/sub'), [])
  assert.deepEqual(marksAfterNavigate(['a.xlsx'], '/d', '/d'), ['a.xlsx'])
})
