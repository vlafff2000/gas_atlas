import test from 'node:test'
import assert from 'node:assert/strict'
import { tableCells } from '../src/categoryLabel.ts'

const table = { rows: ['р'], columns: ['а', 'б'], cells: [['3', '0']], colors: [], swatches: false,
  wells: [[['1', '2', '3', '40', '50', '60', '70', '80'], []]] }

test('таблица под графиком: число или номера скважин (общие примеры с ChartTable.shown)', () => {
  assert.deepEqual(tableCells(table, undefined), [['3', '0']])
  assert.deepEqual(tableCells(table, 'count'), [['3', '0']])
  assert.deepEqual(tableCells(table, 'wells'), [['1, 2, 3, 40, 50, 60,\n70, 80', '0']])
})
