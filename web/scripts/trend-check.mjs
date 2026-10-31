// Контрольные значения линий тренда экрана (web/src/trend.ts); их же считает atlas/trend.py (tests/atlas/test_trend.py сверяет).
// Запуск: node --experimental-strip-types web/scripts/trend-check.mjs
import { fitTrend } from '../src/trend.ts'

const x = [1, 2, 3, 4, 5, 6], y = [2.1, 3.9, 6.2, 7.8, 10.1, 12.0]
const dates = ['2024-01-01', '2024-01-11', '2024-01-21', '2024-02-01', '2024-02-10', '2024-02-20']
const out = {}
for (const [name, kind, order, period] of [['linear', 'linear'], ['poly2', 'poly', 2], ['poly3', 'poly', 3], ['log', 'log'], ['power', 'power'], ['exp', 'exp'], ['moving', 'moving', 2, 3]]) {
  const f = fitTrend(kind, x, y, order, period)
  out[name] = f && { equation: f.equation, r2: f.r2, n: f.x.length, first: f.y[0], last: f.y[f.y.length - 1] }
}
const t = fitTrend('linear', dates, y)
out.time = t && { equation: t.equation, r2: t.r2, n: t.x.length, first: t.y[0], last: t.y[t.y.length - 1] }
console.log(JSON.stringify(out))
