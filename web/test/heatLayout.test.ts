import test from 'node:test'
import assert from 'node:assert/strict'
import { heatLayout, rowOrder, total, totalText } from '../src/heatLayout.ts'

// Те же примеры, что в tests/atlas/test_heat_scale.py::test_heat_layout_order_and_totals (зеркало atlas/heat_layout.py).
const rows = ['ГСП 10', 'ГСП 2', 'ГСП 1'], values: (number | null)[][] = [[1, null], [5, 5], [2, 3]]

test('порядок строк', () => {
  assert.deepEqual(rowOrder(rows, values), [0, 1, 2])
  assert.deepEqual(rowOrder(rows, values, 'sum'), [1, 2, 0])
  assert.deepEqual(rowOrder(rows, values, 'name'), [2, 1, 0])
})

test('итоги', () => {
  assert.equal(total([1, null, 2], 'sum'), 3)
  assert.equal(total([1, null, 2], 'mean'), 1.5)
  assert.equal(total([null], 'sum'), null)
  const lay = heatLayout(rows, values, { heat_sort: 'sum', heat_totals: 'both', heat_total: 'mean' })
  assert.deepEqual(lay.order, [1, 2, 0])
  assert.deepEqual(lay.rowTotals, [5, 2.5, 1])
  assert.equal(lay.colTotals?.[0], 8 / 3)
  assert.equal(heatLayout(rows, values, {}).rowTotals, null)
  assert.equal(totalText(12), '12')
  assert.equal(totalText(null), '')
})
