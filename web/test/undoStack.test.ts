import test from 'node:test'
import assert from 'node:assert/strict'
import { UndoStack, undoKey } from '../src/undoStack.ts'

test('отмена и повтор идут в обратном порядке', async () => {
  let v = 0
  const s = new UndoStack()
  v = 1; s.push({ label: 'один', undo: () => { v = 0 }, redo: () => { v = 1 } })
  v = 2; s.push({ label: 'два', undo: () => { v = 1 }, redo: () => { v = 2 } })
  assert.equal(await s.undo(), 'два'); assert.equal(v, 1)
  assert.equal(await s.undo(), 'один'); assert.equal(v, 0)
  assert.equal(await s.undo(), null)
  assert.equal(await s.redo(), 'один'); assert.equal(v, 1)
  s.push({ label: 'три', undo: () => { v = 1 } })
  assert.equal(s.canRedo, false)
})

test('быстрые правки с одним ключом склеиваются, исходное «до» сохраняется', async () => {
  let v = 'a'
  const s = new UndoStack(50, 700)
  v = 'b'; s.push({ label: 'текст', key: 'k', undo: () => { v = 'a' }, redo: () => { v = 'b' } }, 1000)
  v = 'c'; s.push({ label: 'текст', key: 'k', undo: () => { v = 'b' }, redo: () => { v = 'c' } }, 1300)
  assert.equal(s.size, 1)
  await s.undo(); assert.equal(v, 'a')
  await s.redo(); assert.equal(v, 'c')
  v = 'd'; s.push({ label: 'текст', key: 'k', undo: () => { v = 'c' } }, 5000)
  assert.equal(s.size, 2)
})

test('предел глубины; сбой отката оставляет запись в стеке', async () => {
  const s = new UndoStack(2)
  for (let i = 0; i < 5; i++) s.push({ label: String(i), undo: () => {} })
  assert.equal(s.size, 2)
  const f = new UndoStack()
  f.push({ label: 'x', undo: () => { throw new Error('нет связи') } })
  await assert.rejects(f.undo(), /нет связи/)
  assert.equal(f.canUndo, true)
})

test('горячие клавиши: в текстовых полях отмена браузера', () => {
  const base = { ctrlKey: true, metaKey: false, shiftKey: false, altKey: false }
  assert.equal(undoKey({ ...base, key: 'z', target: { tagName: 'DIV' } }), 'undo')
  assert.equal(undoKey({ ...base, key: 'Z', shiftKey: true, target: { tagName: 'BODY' } }), 'redo')
  assert.equal(undoKey({ ...base, key: 'y', target: { tagName: 'BODY' } }), 'redo')
  assert.equal(undoKey({ ...base, key: 'z', target: { tagName: 'INPUT', type: 'text' } }), null)
  assert.equal(undoKey({ ...base, key: 'z', target: { tagName: 'INPUT', type: 'checkbox' } }), 'undo')
  assert.equal(undoKey({ ...base, ctrlKey: false, key: 'z' }), null)
})
