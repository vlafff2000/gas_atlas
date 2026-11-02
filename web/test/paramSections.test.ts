import { test } from 'node:test'
import assert from 'node:assert/strict'
import { groupSections } from '../src/paramSections.ts'

const P = (name: string, section: string) => ({ name, section })

test('перемежающиеся разделы не дублируются при переключении вида', () => {
  const spec = [P('wells', 'Выбор данных'), P('cons', 'Схема скважины'), P('perf', 'Выбор данных'),
    P('art', 'Схема скважины'), P('gis', 'Схема скважины'), P('start', 'Выбор данных')]
  // повторное переключение «Планшет → Конструкция» даёт тот же результат, блоки не копятся
  for (let i = 0; i < 3; i++) {
    const g = groupSections(spec)
    assert.deepEqual(g.map(s => s[0]), ['Выбор данных', 'Схема скважины'])
    assert.deepEqual(g[0][1].map(p => p.name), ['wells', 'perf', 'start'])
    assert.deepEqual(g[1][1].map(p => p.name), ['cons', 'art', 'gis'])
  }
})
