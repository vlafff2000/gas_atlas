import test from 'node:test'
import assert from 'node:assert/strict'
import { stepWell } from '../src/wellStep.ts'

test('стрелки листают скважины и останавливаются на краях', () => {
  const ws = ['101', '102', '103']
  assert.equal(stepWell(ws, '102', 1), '103')
  assert.equal(stepWell(ws, '102', -1), '101')
  assert.equal(stepWell(ws, '103', 1), '103')
  assert.equal(stepWell(ws, '101', -1), '101')
  assert.equal(stepWell(ws, 'нет', 1), '101')
  assert.equal(stepWell([], '1', 1), undefined)
})
