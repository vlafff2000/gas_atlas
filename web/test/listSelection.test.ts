import { test } from 'node:test'
import assert from 'node:assert/strict'
import { clickRow, emptyHighlight, moveCursor, selectAll, toggleHighlighted } from '../src/listSelection.ts'

const list = ['1', '2', '3', '4', '5']
const rows = (h: { rows: Set<string> }) => [...h.rows].sort()

test('щелчок, Ctrl и Shift выделяют строки как в 5.8', () => {
  let h = clickRow(emptyHighlight(), list, 1, false, false)
  assert.deepEqual(rows(h), ['2'])
  h = clickRow(h, list, 3, true, false)                 // Shift: диапазон 2–4
  assert.deepEqual(rows(h), ['2', '3', '4'])
  h = clickRow(h, list, 0, false, true)                 // Ctrl: добавить 1
  assert.deepEqual(rows(h), ['1', '2', '3', '4'])
  h = clickRow(h, list, 2, false, true)                 // Ctrl по выделенной: убрать
  assert.deepEqual(rows(h), ['1', '2', '4'])
  h = clickRow(h, list, 4, true, true)                  // Ctrl+Shift: добавить диапазон от якоря (3) до 5
  assert.deepEqual(rows(h), ['1', '2', '3', '4', '5'])
  assert.deepEqual(rows(clickRow(h, list, 4, false, false)), ['5'])
})

test('Пробел ставит флажки всей выделенной группе, повторный — снимает', () => {
  const h = clickRow(clickRow(emptyHighlight(), list, 1, false, false), list, 3, true, false)
  const on = toggleHighlighted(list, ['5'], h, list, 1)
  assert.deepEqual(on, ['2', '3', '4', '5'])
  assert.deepEqual(toggleHighlighted(list, on, h, list, 1), ['5'])
  assert.deepEqual(toggleHighlighted(list, ['3'], h, list, 1), ['2', '3', '4']) // смешанная группа — ставит всем
})

test('Пробел без выделения меняет строку под курсором; скрытые поиском строки не трогает', () => {
  assert.deepEqual(toggleHighlighted(list, [], emptyHighlight(), list, 2), ['3'])
  assert.deepEqual(toggleHighlighted(list, [], selectAll(list, 0), ['2', '4'], 0), ['2', '4'])
})

test('стрелки двигают курсор, Shift+стрелка расширяет диапазон', () => {
  let { highlight, cursor } = moveCursor(emptyHighlight(), list, 0, 1, false)
  assert.equal(cursor, 1); assert.deepEqual(rows(highlight), ['2'])
  ;({ highlight, cursor } = moveCursor(highlight, list, cursor, 1, true))
  ;({ highlight, cursor } = moveCursor(highlight, list, cursor, 1, true))
  assert.equal(cursor, 3); assert.deepEqual(rows(highlight), ['2', '3', '4'])
  assert.equal(moveCursor(highlight, list, 4, 1, false).cursor, 4)
})
