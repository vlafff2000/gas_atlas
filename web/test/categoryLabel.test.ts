import { test } from 'node:test'
import assert from 'node:assert/strict'
import { categoryLabel, wrapText } from '../src/categoryLabel.ts'

test('перенос по словам: общие примеры с atlas/category_labels.py', () => {
  assert.equal(wrapText('ГСП 1 северная часть', 8), 'ГСП 1\nсеверная\nчасть')
  assert.equal(wrapText('Сверхдлинное слово', 5), 'Сверхдлинное\nслово')
  assert.equal(wrapText('первая\nвторая строка', 8), 'первая\nвторая\nстрока')
  assert.equal(wrapText('как есть', 0), 'как есть')
})

test('переименование, затем перенос', () => {
  const spec = { category_names: { 'ГСП-1': 'Северная часть залежи' }, category_wrap: 10 }
  assert.equal(categoryLabel('ГСП-1', spec), 'Северная\nчасть\nзалежи')
  assert.equal(categoryLabel('ГСП-2', spec), 'ГСП-2')
})
