import test from 'node:test'
import assert from 'node:assert/strict'
import { wheelHintDue } from '../src/chartAxes.ts'

const plain = { ctrlKey: false, metaKey: false }

test('подсказка: колесо без Ctrl, курсор постоял над графиком, прошлый показ давно', () => {
  assert.equal(wheelHintDue(plain, 1000, 600, -Infinity), true)
})

test('подсказка не показывается при пролёте страницы мимо графика', () => {
  assert.equal(wheelHintDue(plain, 1000, 900, -Infinity), false)
})

test('подсказка не мигает чаще, чем раз в несколько секунд', () => {
  assert.equal(wheelHintDue(plain, 3000, 0, 1000), false)
  assert.equal(wheelHintDue(plain, 6000, 0, 1000), true)
})

test('с Ctrl подсказка не нужна: график масштабируется', () => {
  assert.equal(wheelHintDue({ ctrlKey: true, metaKey: false }, 1000, 0, -Infinity), false)
})
