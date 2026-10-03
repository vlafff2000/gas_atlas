// Плавная подсказка графика: значения кривых между замерами (линейная интерполяция), ближайшая точка
// с запасом в несколько пикселей для щелчка и выбор кривой, к которой ближе курсор. Чистые функции без DOM,
// чтобы не зависеть от отрисовки и работать на миллионе точек: поиск двоичный, пиксели считаются только у кандидатов.
import type { Axis, Cell, Series } from './api'

export interface Track {
  index: number                 // номер серии в chart.series и в option.series
  series: Series
  axis: 0 | 1                   // 1 — вторая шкала справа
  xs: Float64Array              // x без пустых, по возрастанию, если monotonic
  ys: Float64Array              // NaN — разрыв линии
  src: Uint32Array              // номер исходной точки (для ids и labels)
  monotonic: boolean
  curve: boolean                // линия: значение между замерами интерполируется
  points: boolean               // отдельные отметки: на них можно навести и щёлкнуть
  bar: boolean
  order: Uint32Array | null     // порядок по x для поиска точек, когда x не возрастает
}

export interface View {
  toPixel: (x: number, y: number, axis: 0 | 1) => [number, number]
  fromPixel: (px: number, py: number) => [number, number]
  visible: (t: Track) => boolean
}

export interface PointHit { track: Track; k: number; x: number; y: number; px: number; py: number; distance: number }
export interface CurveValue { track: Track; x: number; y: number; px: number; py: number; k: number; distance: number }
export interface Hover { x: number; point: PointHit | null; values: CurveValue[]; focus: CurveValue | null }

const ISO_NO_ZONE = /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

/** Значение ячейки как число оси: время — мс UTC (дата без зоны считается UTC, как подписи осей). */
export function toNumber(v: Cell, scale: Axis['scale']): number {
  if (v === null || v === undefined || v === '') return NaN
  // время числом: мс; наносекунды (так приходят даты из фигур Plotly 5.8) приводятся к мс
  if (typeof v === 'number') return scale === 'time' && Math.abs(v) > 1e14 ? v / 1e6 : v
  if (scale === 'time' && typeof v === 'string') return Date.parse(ISO_NO_ZONE.test(v) ? v + 'Z' : v)
  const n = Number(v)
  return Number.isFinite(n) ? n : NaN
}

/** marked — видны ли на линии отметки замеров (на них наводят и щёлкают). */
export function buildTracks(series: Series[], x: Axis, y2: boolean, marked: (s: Series) => boolean = s => s.markers): Track[] {
  if (x.scale === 'category') return []
  const tracks: Track[] = []
  series.forEach((s, index) => {
    if (s.kind === 'box') return
    const n = s.x.length
    const xs = new Float64Array(n), ys = new Float64Array(n), src = new Uint32Array(n)
    let m = 0, monotonic = true, last = -Infinity
    for (let j = 0; j < n; j++) {
      const xv = toNumber(s.x[j], x.scale)
      if (!Number.isFinite(xv)) continue
      const yv = typeof s.y[j] === 'number' ? (s.y[j] as number) : toNumber(s.y[j], 'value')
      if (s.kind !== 'line' && !Number.isFinite(yv)) continue
      if (xv < last) monotonic = false
      last = xv
      xs[m] = xv; ys[m] = yv; src[m] = j; m++
    }
    if (!m) return
    const track: Track = {
      index, series: s, axis: s.axis === 'y2' && y2 ? 1 : 0,
      xs: xs.subarray(0, m), ys: ys.subarray(0, m), src: src.subarray(0, m), monotonic,
      curve: s.kind === 'line', bar: s.kind === 'bar',
      points: s.kind === 'points' || (s.kind === 'line' && marked(s)),
      order: null,
    }
    if (!monotonic && track.points) {
      const order = Uint32Array.from({ length: m }, (_, i) => i)
      order.sort((a, b) => track.xs[a] - track.xs[b])
      track.order = order
    }
    tracks.push(track)
  })
  return tracks
}

/** Первый номер k, у которого xs[k] >= v (xs по возрастанию, или через порядок order). */
function lowerBound(xs: Float64Array, v: number, order: Uint32Array | null) {
  let lo = 0, hi = xs.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (xs[order ? order[mid] : mid] < v) lo = mid + 1; else hi = mid
  }
  return lo
}

const POINT_RADIUS = 14       // пикселей вокруг отметки: в неё легко попасть
const FOCUS_RADIUS = 48       // кривая ближе этого — выделяется и стоит в подсказке первой
const SCAN_LIMIT = 6000       // кандидатов на точку за одно движение — хватает с запасом и на плотном облаке
const FREE_LIMIT = 20000      // линию с невозрастающим x ищем перебором отрезков только до этого размера

/** smooth — значение между замерами (интерполяция); facts — только фактические замеры, без домысливания. */
export type HoverMode = 'smooth' | 'facts'

const FACT_RADIUS = 32        // в режиме замеров кривая показывается, если её замер не дальше этого по x

export function hover(tracks: Track[], view: View, px: number, py: number, scaleX: Axis['scale'],
  scaleY: (axis: 0 | 1) => Axis['scale'], mode: HoverMode = 'smooth'): Hover {
  const [dx] = view.fromPixel(px, py)
  const [dxR] = view.fromPixel(px + POINT_RADIUS, py)
  const [dxL] = view.fromPixel(px - POINT_RADIUS, py)
  const lo = Math.min(dxL, dxR), hi = Math.max(dxL, dxR)
  let point: PointHit | null = null
  const values: CurveValue[] = []
  const lx = scaleX === 'log'

  for (const t of tracks) {
    if (!view.visible(t)) continue
    const { xs, ys, order } = t
    // ближайшая отметка в радиусе
    if (t.points) {
      const ord = t.monotonic ? null : order
      let k = lowerBound(xs, lo, ord)
      for (let scanned = 0; k < xs.length && scanned < SCAN_LIMIT; k++, scanned++) {
        const i = ord ? ord[k] : k
        if (xs[i] > hi) break
        if (!Number.isFinite(ys[i])) continue
        const [qx, qy] = view.toPixel(xs[i], ys[i], t.axis)
        const d = Math.hypot(qx - px, qy - py)
        if (d <= POINT_RADIUS && (!point || d < point.distance)) point = { track: t, k: i, x: xs[i], y: ys[i], px: qx, py: qy, distance: d }
      }
    }
    // значение кривой под курсором
    if (t.curve && mode === 'facts') {
      // ближайший фактический замер кривой по x (линия без порядка — по расстоянию на экране)
      let best: CurveValue | null = null
      const consider = (i: number) => {
        if (i < 0 || i >= xs.length || !Number.isFinite(ys[i])) return
        const [qx, qy] = view.toPixel(xs[i], ys[i], t.axis)
        const d = t.monotonic ? Math.abs(qx - px) : Math.hypot(qx - px, qy - py)
        if (d <= (t.monotonic ? FACT_RADIUS : FOCUS_RADIUS) && (!best || d < best.distance)) best = { track: t, x: xs[i], y: ys[i], px: qx, py: qy, k: i, distance: d }
      }
      if (t.monotonic) {
        const k = lowerBound(xs, dx, null)
        // соседние замеры могут быть разрывами (NaN): ищем ближайшие заполненные в обе стороны
        let a = k - 1, b = k
        while (a >= 0 && !Number.isFinite(ys[a])) a--
        while (b < xs.length && !Number.isFinite(ys[b])) b++
        consider(a); consider(b)
      } else if (xs.length <= FREE_LIMIT) for (let i = 0; i < xs.length; i++) consider(i)
      const found = best as CurveValue | null
      if (found) values.push({ ...found, distance: Math.abs(found.py - py) })
    } else if (t.curve && t.monotonic) {
      const k = lowerBound(xs, dx, null)
      let x = NaN, y = NaN, near = k
      if (k < xs.length && xs[k] === dx) { x = dx; y = ys[k] }
      else if (k > 0 && k < xs.length && Number.isFinite(ys[k - 1]) && Number.isFinite(ys[k])) {
        const ly = scaleY(t.axis) === 'log'
        const a = lx ? Math.log(xs[k - 1]) : xs[k - 1], b = lx ? Math.log(xs[k]) : xs[k]
        const f = b === a ? 0 : ((lx ? Math.log(dx) : dx) - a) / (b - a)
        y = ly ? Math.exp(Math.log(ys[k - 1]) + f * (Math.log(ys[k]) - Math.log(ys[k - 1])))
          : ys[k - 1] + f * (ys[k] - ys[k - 1])
        x = dx
        near = f < 0.5 ? k - 1 : k
      }
      if (Number.isFinite(y)) {
        const [qx, qy] = view.toPixel(x, y, t.axis)
        values.push({ track: t, x, y, px: qx, py: qy, k: near, distance: Math.abs(qy - py) })
      }
    } else if (t.curve && xs.length <= FREE_LIMIT) {
      // линия без порядка по x: проекция курсора на ближайший отрезок
      let best: CurveValue | null = null
      let [ax, ay] = view.toPixel(xs[0], ys[0], t.axis)
      for (let i = 1; i < xs.length; i++) {
        const [bx, by] = view.toPixel(xs[i], ys[i], t.axis)
        if (Number.isFinite(ay) && Number.isFinite(by)) {
          const vx = bx - ax, vy = by - ay, len = vx * vx + vy * vy
          const f = len ? Math.max(0, Math.min(1, ((px - ax) * vx + (py - ay) * vy) / len)) : 0
          const qx = ax + f * vx, qy = ay + f * vy, d = Math.hypot(qx - px, qy - py)
          if (!best || d < best.distance) {
            best = { track: t, x: xs[i - 1] + f * (xs[i] - xs[i - 1]), y: ys[i - 1] + f * (ys[i] - ys[i - 1]),
              px: qx, py: qy, k: f < 0.5 ? i - 1 : i, distance: d }
          }
        }
        ax = bx; ay = by
      }
      if (best && best.distance <= FOCUS_RADIUS) values.push(best)
    } else if (t.bar) {
      // столбец на оси значений или времени: ближайший по x в пределах половины шага
      const k = lowerBound(xs, dx, null)
      const cands = [k - 1, k].filter(i => i >= 0 && i < xs.length && Number.isFinite(ys[i]))
      let best: CurveValue | null = null
      for (const i of cands) {
        const [qx, qy] = view.toPixel(xs[i], ys[i], t.axis)
        const j = i + 1 < xs.length ? i + 1 : i - 1
        const step = j >= 0 && j !== i ? Math.abs(view.toPixel(xs[j], ys[j], t.axis)[0] - qx) : 80
        const d = Math.abs(qx - px)
        if (d <= Math.max(8, step / 2) && (!best || d < best.distance)) best = { track: t, x: xs[i], y: ys[i], px: qx, py: qy, k: i, distance: d }
      }
      if (best) values.push({ ...best, distance: Math.abs(best.py - py) })
    }
  }
  let focus: CurveValue | null = null
  for (const v of values) if (v.track.curve && v.distance <= FOCUS_RADIUS && (!focus || v.distance < focus.distance)) focus = v
  return { x: dx, point, values, focus }
}

/** Разумная точность подписи: по размаху оси, без лишних знаков у интерполированных значений. */
export function decimalsFor(span: number) {
  if (!Number.isFinite(span) || span <= 0) return 2
  return Math.max(0, Math.min(6, -Math.floor(Math.log10(span / 1000))))
}
