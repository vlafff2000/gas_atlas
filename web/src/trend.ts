// Линии тренда ряда: та же математика, что в atlas/trend.py (контрольные значения сверяются в tests/atlas/test_trend.py
// и web/scripts/trend-check.mjs). Виды как в Excel: линейная, полином 2–6, логарифмическая, степенная, экспоненциальная, скользящее.
import type { Cell, Series } from './api'

export type TrendKind = 'linear' | 'poly' | 'log' | 'power' | 'exp' | 'moving'
export interface TrendFit { x: number[]; y: number[]; equation: string; r2: number | null }
const POINTS = 120

const fmt = (v: number) => String(Number(v.toPrecision(4))).replace('.', ',')
const SUP = '⁰¹²³⁴⁵⁶'

/** Числа точек ряда: дата — миллисекунды (time = true); пары с пропуском отбрасываются, остальные упорядочены по X. */
function points(x: Cell[], y: Cell[]): { x: number[]; y: number[]; time: boolean } {
  const ys = y.map(v => (typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v.replace(',', '.')) : NaN))
  let xs = x.map(v => (typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v.replace(',', '.')) : NaN))
  let time = false
  if (xs.length && xs.every(Number.isNaN)) { xs = x.map(v => (typeof v === 'string' ? Date.parse(v) : NaN)); time = true }
  const idx = xs.map((_, i) => i).filter(i => Number.isFinite(xs[i]) && Number.isFinite(ys[i] ?? NaN)).sort((a, b) => xs[a] - xs[b] || a - b)
  return { x: idx.map(i => xs[i]), y: idx.map(i => ys[i]), time }
}

/** Решение A·c = b методом Гаусса с выбором главного элемента. */
function solve(a: number[][], b: number[]): number[] {
  const n = b.length
  for (let i = 0; i < n; i++) {
    let p = i
    for (let r = i + 1; r < n; r++) if (Math.abs(a[r][i]) > Math.abs(a[p][i])) p = r
    ;[a[i], a[p]] = [a[p], a[i]]; [b[i], b[p]] = [b[p], b[i]]
    for (let r = i + 1; r < n; r++) {
      const f = a[r][i] / a[i][i]
      for (let c = i; c < n; c++) a[r][c] -= f * a[i][c]
      b[r] -= f * b[i]
    }
  }
  const c = new Array<number>(n).fill(0)
  for (let i = n - 1; i >= 0; i--) {
    let s = b[i]
    for (let j = i + 1; j < n; j++) s -= a[i][j] * c[j]
    c[i] = s / a[i][i]
  }
  return c
}

/** Коэффициенты многочлена степени deg по u (от старшей степени), метод наименьших квадратов. */
function polyfit(u: number[], z: number[], deg: number): number[] {
  const a = Array.from({ length: deg + 1 }, () => new Array<number>(deg + 1).fill(0)), b = new Array<number>(deg + 1).fill(0)
  u.forEach((ui, k) => {
    const pw = [1]
    for (let j = 1; j <= 2 * deg; j++) pw.push(pw[j - 1] * ui)
    for (let i = 0; i <= deg; i++) { b[i] += pw[i] * z[k]; for (let j = 0; j <= deg; j++) a[i][j] += pw[i + j] }
  })
  return solve(a, b).reverse()
}
const polyval = (c: number[], u: number) => c.reduce((acc, v) => acc * u + v, 0)
const comb = (n: number, k: number) => { let r = 1; for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i; return Math.round(r) }

/** Коэффициенты по x из коэффициентов по u = (x − m) / s (от старшей степени). */
function rawPoly(cu: number[], m: number, s: number): number[] {
  const deg = cu.length - 1, out = new Array<number>(deg + 1).fill(0)
  for (let k = 0; k <= deg; k++) {
    const ck = cu[deg - k] / s ** k
    for (let j = 0; j <= k; j++) out[j] += ck * comb(k, j) * (-m) ** (k - j)
  }
  return out.reverse()
}

function polyText(c: number[]): string {
  const n = c.length - 1, terms: [string, string][] = []
  c.forEach((v, i) => {
    const p = n - i
    if (v === 0) return
    terms.push([v < 0 ? '−' : '+', fmt(Math.abs(v)) + (p === 0 ? '' : 'x' + (p === 1 ? '' : SUP[p]))])
  })
  if (!terms.length) return 'y = 0'
  return 'y = ' + (terms[0][0] === '−' ? '−' : '') + terms[0][1] + terms.slice(1).map(([s, b]) => ` ${s} ${b}`).join('')
}

export function fitTrend(kind: TrendKind, xs: Cell[], ys: Cell[], order = 2, period = 5): TrendFit | null {
  const { x, y, time } = points(xs, ys)
  if (x.length < 2) return null
  if (kind === 'moving') {
    const w = Math.trunc(period)
    if (w < 2 || x.length < w) return null
    const ox: number[] = [], oy: number[] = []
    for (let i = w - 1; i < x.length; i++) { ox.push(x[i]); oy.push(y.slice(i - w + 1, i + 1).reduce((a, b) => a + b, 0) / w) }
    return { x: ox, y: oy, equation: `скользящее среднее, ${w}`, r2: null }
  }
  const lo = x[0], hi = x[x.length - 1]
  if (hi === lo) return null
  if ((kind === 'log' || kind === 'power') && x.some(v => v <= 0)) return null
  if ((kind === 'power' || kind === 'exp') && y.some(v => v <= 0)) return null
  const deg = kind === 'poly' ? Math.trunc(order) : 1
  if (kind === 'poly' && (deg < 2 || deg > 6 || x.length <= deg)) return null
  const lg = kind === 'log' || kind === 'power'
  const tx = x.map(v => (lg ? Math.log(v) : v))
  const center = lg ? tx.reduce((a, b) => a + b, 0) / tx.length : x.reduce((a, b) => a + b, 0) / x.length
  const scale = (Math.max(...tx) - Math.min(...tx)) / 2
  const z = y.map(v => (kind === 'power' || kind === 'exp' ? Math.log(v) : v))
  const cu = polyfit(tx.map(v => (v - center) / scale), z, deg)
  const predict = (v: number) => { const q = polyval(cu, ((lg ? Math.log(v) : v) - center) / scale); return kind === 'power' || kind === 'exp' ? Math.exp(q) : q }
  const mean = y.reduce((a, b) => a + b, 0) / y.length
  const sst = y.reduce((a, v) => a + (v - mean) ** 2, 0), sse = y.reduce((a, v, i) => a + (v - predict(x[i])) ** 2, 0)
  const r2 = sst > 0 ? 1 - sse / sst : 1
  const gx = Array.from({ length: POINTS }, (_, i) => lo + ((hi - lo) * i) / (POINTS - 1))
  let equation = ''
  if (!time) {
    const raw = rawPoly(cu, center, scale)
    if (kind === 'linear' || kind === 'poly') equation = polyText(raw)
    else if (kind === 'log') equation = `y = ${fmt(raw[0])} ln(x) ${raw[1] < 0 ? '−' : '+'} ${fmt(Math.abs(raw[1]))}`
    else if (kind === 'power') equation = `y = ${fmt(Math.exp(raw[1]))}x^${fmt(raw[0])}`
    else equation = `y = ${fmt(Math.exp(raw[1]))}e^(${fmt(raw[0])}x)`
  }
  return { x: gx, y: gx.map(predict), equation, r2 }
}

export const trendLabel = (name: string, f: TrendFit, show: boolean): string => {
  const extra = show ? [f.equation, f.r2 === null ? '' : `R² = ${fmt(f.r2)}`].filter(Boolean) : []
  return `Тренд: ${name}` + (extra.length ? ` (${extra.join('; ')})` : '')
}

/** Линии тренда рядов, у которых в виде задан trend (как atlas/chart_style._trends). Тренд ряда без подходящих точек пропускается. */
export function trendSeries(series: Series[]): Series[] {
  const out: Series[] = []
  for (const s of series) {
    const look = s.look
    if (!look?.trend || (s.kind !== 'points' && s.kind !== 'line') || s.name.startsWith('Тренд: ') || series.some(t => t.name.startsWith('Тренд: ' + s.name))) continue
    const f = fitTrend(look.trend, s.x, s.y, look.trend_order ?? 2, look.trend_period ?? 5)
    if (!f) continue
    out.push({ ...s, name: trendLabel(s.name, f, !!look.trend_label), kind: 'line', group: s.group || s.name, dashed: false, dash: 'dash',
      width: look.trend_width ?? (Math.max(s.width, 1.5)), legend: false, color: look.trend_color ?? s.color, look: undefined,
      tooltip: trendLabel(s.name, f, true), x: f.x, y: f.y, ids: null, labels: null, dataset: null, markers: false, hollow: false,
      total: f.x.length, facets: null, captions: null, values: null, suspect: false, fill: false, step: false, stack: '' })
  }
  return out
}
