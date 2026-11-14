import test from 'node:test'
import assert from 'node:assert/strict'
import { isHelpKey, SHORTCUTS } from '../src/shortcuts.ts'

const key = (over: Record<string, unknown> = {}) => ({ key: '?', ctrlKey: false, metaKey: false, altKey: false, target: null, ...over })

test('«?» и F1 открывают шпаргалку', () => {
  assert.equal(isHelpKey(key()), true)
  assert.equal(isHelpKey(key({ key: 'F1' })), true)
})

test('в поле ввода «?» остаётся символом', () => {
  assert.equal(isHelpKey(key({ target: { tagName: 'INPUT' } })), false)
  assert.equal(isHelpKey(key({ target: { tagName: 'TEXTAREA' } })), false)
  assert.equal(isHelpKey(key({ target: { tagName: 'DIV', isContentEditable: true } })), false)
})

test('с Ctrl, ⌘ и Alt шпаргалка не открывается', () => {
  assert.equal(isHelpKey(key({ ctrlKey: true })), false)
  assert.equal(isHelpKey(key({ metaKey: true })), false)
})

test('в списке сочетаний нет повторов и пустых описаний', () => {
  const keys = SHORTCUTS.map(s => s.group + s.keys)
  assert.equal(new Set(keys).size, keys.length)
  assert.ok(SHORTCUTS.every(s => s.keys && s.text && s.group))
})
