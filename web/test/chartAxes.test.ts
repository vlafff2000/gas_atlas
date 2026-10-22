import test from 'node:test'
import assert from 'node:assert/strict'
import { fitAxisName } from '../src/chartAxes.ts'

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
