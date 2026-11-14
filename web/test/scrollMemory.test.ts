import test from 'node:test'
import assert from 'node:assert/strict'
import { scrollRestore } from '../src/scrollMemory.ts'

test('прокрутка: страница достаточно высока — возвращаемся точно', () => {
  assert.deepEqual(scrollRestore(1200, 4000, 800), { y: 1200, done: true })
})

test('прокрутка: страница ещё не доросла (графики дорисовываются) — идём до конца и ждём', () => {
  assert.deepEqual(scrollRestore(1200, 1500, 800), { y: 700, done: false })
})

test('прокрутка: нечего восстанавливать (нет записи, ноль, мусор)', () => {
  for (const saved of [null, 0, -5, NaN]) assert.deepEqual(scrollRestore(saved, 4000, 800), { y: 0, done: true })
})
