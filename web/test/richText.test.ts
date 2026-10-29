import test from 'node:test'
import assert from 'node:assert/strict'
import { echartsRich, parseRich, plainRich, richFromSegs, richHtml } from '../src/richText.ts'

test('разбор: теги индексов задают начертание кускам текста', () => {
  assert.deepEqual(parseRich('CO<sub>2</sub>, м<sup>3</sup>'), [
    { text: 'CO', sup: false, sub: false },
    { text: '2', sup: false, sub: true },
    { text: ', м', sup: false, sub: false },
    { text: '3', sup: true, sub: false },
  ])
})

test('незакрытый тег действует до конца строки', () => {
  assert.deepEqual(parseRich('a<sup>b'), [{ text: 'a', sup: false, sub: false }, { text: 'b', sup: true, sub: false }])
})

test('plainRich убирает только теги индексов', () => {
  assert.equal(plainRich('Q<sub>ж</sub> <b>x</b>'), 'Qж <b>x</b>')
})

test('richFromSegs собирает строку обратно без лишних тегов', () => {
  const segs = [{ text: 'H', sup: false, sub: false }, { text: '2', sup: false, sub: true }, { text: 'O', sup: false, sub: false }]
  assert.equal(richFromSegs(segs), 'H<sub>2</sub>O')
  assert.equal(richFromSegs(parseRich('x<sup>1</sup>')), 'x<sup>1</sup>')
})

test('richHtml экранирует текст и оставляет индексы', () => {
  assert.equal(richHtml('a & Q<sub>ж</sub>'), 'a &amp; Q<sub>ж</sub>')
  assert.equal(richHtml('P<sup>2</sup> <i>'), 'P<sup>2</sup> &lt;i&gt;')
})

test('echartsRich: индексы — стили rich, размер 70 %', () => {
  const r = echartsRich('Q<sub>ж</sub>, м<sup>3</sup>', 12)
  assert.equal(r.text, 'Q{sub|ж}, м{sup|3}')
  assert.deepEqual(r.rich, {
    sup: { fontSize: 8.4, verticalAlign: 'top' },
    sub: { fontSize: 8.4, verticalAlign: 'bottom' },
  })
})
