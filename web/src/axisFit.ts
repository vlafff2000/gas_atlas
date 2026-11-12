// Единый автоподбор шкал значений — зеркало atlas/axis_fit.py (правила и пояснения там). Нужен экрану, чтобы правка оси в
// панели «Формат» (режим, граница, шаг) пересчитывала шкалы сразу, без запроса к серверу, и давала те же числа, что файл.
// Обе реализации проверяются одной таблицей tests/fixtures/axis_fit_cases.json: правка здесь без правки там ломает тесты.

import type { Axis, Chart } from './api'

export type FitMode = 'auto' | 'zero' | 'data'
export interface Need {
  lo?: number | null; hi?: number | null; anchor?: boolean; mode?: FitMode
  minimum?: number | null; maximum?: number | null; step?: number | null; inverse?: boolean
  /** запас срезанной шкалы со стороны нуля, в долях размаха; у оси X — 0 */
  margin?: number
}
export interface Fit { minimum: number; maximum: number; step: number; n: number | null; zero: boolean; why: string }

const MULTS = [1, 2, 2.5, 5]
export const N_MIN = 4, N_MAX = 8, N_PREFERRED = 5
const ZERO_SHARE = 0.25
const MAX_INTERVALS = 150
const N_PENALTY = 0.03
const ODD_PENALTY = 0.02
const ROUGH_FIXED = 0.6
const MARGIN = 0.02
const ALIGN_MIN = 0.5
const EPS = 1e-9

/** Причина выбора пределов словами (те же коды, что atlas/axis_fit.WHY). */
export const WHY: Record<string, string> = {
  anchor: 'столбцы и области растут от нуля — нуль обязателен',
  near: 'нуль рядом с данными — шкала начата от нуля',
  cut: 'данные далеко от нуля — шкала срезана, чтобы кривая занимала поле',
  mixed: 'значения разных знаков — нуль внутри шкалы',
  'mode-zero': 'режим «авто от нуля»',
  'mode-data': 'режим «по данным»',
  flat: 'все значения равны — шкала вокруг значения',
  manual: 'границы заданы вручную',
  step: 'шаг задан вручную — границы кратны шагу',
  empty: 'на шкале нет данных',
}

type Cand = [low: number, high: number, step: number, cover: number, zero: boolean, why: string]

const pow10 = (e: number) => Number(`1e${e}`)

function exponent(value: number): number {
  let e = Math.floor(Math.log10(value))
  while (pow10(e) > value) e -= 1
  while (pow10(e + 1) <= value) e += 1
  return e
}

/** Число без двоичного хвоста: 98.60000000000001 → 98.6. */
export const clean = (value: number) => Number(value.toPrecision(12))

function steps(raw: number): [number, boolean][] {
  const e = exponent(raw)
  const out: [number, boolean][] = []
  for (const k of [e, e + 1, e + 2]) for (const m of MULTS) {
    const s = m * pow10(k)
    if (s >= raw * (1 - EPS)) out.push([s, m === 2.5])
  }
  return out
}

export const niceStep = (raw: number) => steps(raw)[0][0]

export function isNice(step: number): boolean {
  if (!(step > 0)) return false
  const m = step / pow10(exponent(step))
  return MULTS.some(x => Math.abs(m - x) < 1e-6) || Math.abs(m - 10) < 1e-6
}

const halfUp = (x: number) => Math.floor(x + 0.5)

function target(need: Need): [a: number, b: number, zero: boolean, loose: boolean, why: string] {
  let lo = need.lo as number, hi = need.hi as number
  if (lo > hi) [lo, hi] = [hi, lo]
  const flat = hi === lo, span = hi - lo, mode = need.mode ?? 'auto'
  let zero: boolean, why: string
  if (mode === 'zero') { zero = true; why = 'mode-zero' }
  else if (mode === 'data') { zero = lo <= 0 && 0 <= hi; why = 'mode-data' }
  else if (need.anchor) { zero = true; why = 'anchor' }
  else if (lo < 0 && 0 < hi) { zero = true; why = 'mixed' }
  else {
    const gap = lo >= 0 ? lo : -hi
    zero = gap <= span * ZERO_SHARE / (1 - ZERO_SHARE)
    why = zero ? 'near' : flat ? 'flat' : 'cut'
  }
  let a = zero ? Math.min(lo, 0) : lo, b = zero ? Math.max(hi, 0) : hi
  if (b === a) {
    const half = a ? Math.abs(a) * 0.05 : 0.5
    if (!a && zero) { a = 0; b = 1 } else { a -= half; b += half }
    return [a, b, zero, true, why]
  }
  return [a, b, zero, false, why]
}

function free(need: Need, n: number): Cand | null {
  const [a, b, zero, loose, why] = target(need)
  const lo = Math.min(need.lo as number, need.hi as number), hi = Math.max(need.lo as number, need.hi as number)
  const pad = loose || zero ? 0 : (b - a) * (need.margin ?? MARGIN)
  const low = a > 0 ? Math.max(a - pad, 0) : a
  const high = b < 0 ? Math.min(b + pad, 0) : b
  for (const [step, odd] of steps((b - a) / n)) {
    let first = Math.ceil((high - n * step) / step - EPS)
    let last = Math.floor(low / step + EPS)
    if (lo >= 0) first = Math.max(first, 0)
    else if (hi <= 0) last = Math.min(last, -n)
    if (zero && lo >= 0) last = Math.min(last, 0)
    if (zero && hi <= 0 && lo < 0) first = Math.max(first, -n)
    if (first > last) continue
    const m = Math.min(Math.max(halfUp(((a + b) / 2 - n * step / 2) / step), first), last)
    return [m * step, (m + n) * step, step, (b - a) / (n * step) - (odd ? ODD_PENALTY : 0), zero, why]
  }
  return null
}

function half(need: Need, n: number): Cand {
  const [a, b] = target({ lo: need.lo, hi: need.hi, mode: 'data' })
  let low: number, high: number, width: number, step: number, odd: boolean
  if (need.minimum != null) {
    const start = need.minimum, top = Math.max(b, start)
    width = top > start ? top - start : Math.max(Math.abs(start) * 0.1, 1)
    ;[step, odd] = steps(width / n)[0]
    low = start; high = start + n * step
  } else {
    const end = need.maximum as number, bottom = Math.min(a, end)
    width = end > bottom ? end - bottom : Math.max(Math.abs(end) * 0.1, 1)
    ;[step, odd] = steps(width / n)[0]
    low = end - n * step; high = end
  }
  return [low, high, step, width / (n * step) - (odd ? ODD_PENALTY : 0), low <= 0 && 0 <= high, 'manual']
}

function fixed(need: Need, n: number): Cand {
  const low = need.minimum as number, high = need.maximum as number, step = (high - low) / n
  return [low, high, step, isNice(step) ? 1 : ROUGH_FIXED, low <= 0 && 0 <= high, 'manual']
}

function empty(n: number): Cand {
  const step = niceStep(1 / n)
  return [0, n * step, step, 1, true, 'empty']
}

function stepped(need: Need): Fit | null {
  const step = need.step as number
  if (need.lo == null || need.hi == null || !(step > 0)) return null
  const [a, b] = target(need)
  let low = need.minimum != null ? need.minimum : Math.floor(a / step + EPS) * step
  let high = need.maximum != null ? need.maximum : Math.ceil(b / step - EPS) * step
  if (need.minimum == null && Math.min(need.lo, need.hi) >= 0) low = Math.max(low, 0)
  if (!(high > low)) high = low + step
  if ((high - low) / step > MAX_INTERVALS) return null
  return { minimum: clean(low), maximum: clean(high), step, n: null, zero: low <= 0 && 0 <= high, why: 'step' }
}

type Kind = 'skip' | 'stepped' | 'fixed' | 'empty' | 'half' | 'free'

function kindOf(need: Need | null, count: number): Kind {
  if (!need) return 'skip'
  for (const v of [need.lo, need.hi, need.minimum, need.maximum, need.step]) if (v != null && !Number.isFinite(v)) return 'skip'
  const both = need.minimum != null && need.maximum != null
  if (both && !((need.maximum as number) > (need.minimum as number))) return 'skip'
  if (need.step != null) return both ? 'skip' : 'stepped'
  if (both) return count > 1 ? 'fixed' : 'skip'
  if (need.lo == null || need.hi == null) return need.minimum == null && need.maximum == null ? 'empty' : 'skip'
  return need.minimum != null || need.maximum != null ? 'half' : 'free'
}

function zeroIndex(cands: Map<number, Cand>, needs: (Need | null)[], kinds: Kind[], n: number): void {
  const group = [...cands.keys()].filter(i => kinds[i] === 'free' && cands.get(i)![4] && (needs[i]!.mode ?? 'auto') !== 'data')
  if (group.length < 2 || !group.some(i => cands.get(i)![0] < 0 && 0 < cands.get(i)![1])) return
  let best: [number, Map<number, Cand>] | null = null
  for (let k = 0; k <= n; k++) {
    const trial = new Map<number, Cand>()
    let ok = true
    for (const i of group) {
      const need = needs[i]!
      const [a, b, , , why] = target(need)
      const below = need.inverse ? n - k : k
      if ((a < 0 && below === 0) || (b > 0 && below === n)) { ok = false; break }
      const raw = Math.max(below ? -a / below : 0, below < n ? b / (n - below) : 0)
      const [step, odd] = steps(raw)[0]
      trial.set(i, [-below * step, (n - below) * step, step, (b - a) / (n * step) - (odd ? ODD_PENALTY : 0), true, why])
    }
    if (!ok) continue
    const covers = [...trial.values()].map(t => t[3])
    const least = Math.min(...covers)
    const score = 0.5 * least + 0.5 * covers.reduce((s, v) => s + v, 0) / covers.length
    if (least >= ALIGN_MIN && (best === null || score > best[0] + EPS)) best = [score, trial]
  }
  if (best) for (const [i, cand] of best[1]) cands.set(i, cand)
}

/** Границы и шаг всех шкал значений одного графика; null — шкала не подбирается. */
export function fitAxes(needs: (Need | null)[], nMin = N_MIN, nMax = N_MAX, prefer = N_PREFERRED): (Fit | null)[] {
  const count = needs.filter(n => n !== null).length
  const kinds = needs.map(n => kindOf(n, count))
  const out: (Fit | null)[] = needs.map((need, i) => kinds[i] === 'stepped' ? stepped(need!) : null)
  const grid = kinds.map((k, i) => (k === 'free' || k === 'half' || k === 'fixed' || k === 'empty' ? i : -1)).filter(i => i >= 0)
  if (!grid.length) return out
  prefer = Math.min(Math.max(prefer, nMin), nMax)
  const order: number[] = []
  for (let n = nMin; n <= nMax; n++) order.push(n)
  order.sort((p, q) => Math.abs(p - prefer) - Math.abs(q - prefer) || p - q)
  let best: [number, number, Map<number, Cand>] | null = null
  for (const n of order) {
    const cands = new Map<number, Cand>()
    let ok = true
    for (const i of grid) {
      const need = needs[i]!, kind = kinds[i]
      const cand = kind === 'free' ? free(need, n) : kind === 'half' ? half(need, n) : kind === 'fixed' ? fixed(need, n) : empty(n)
      if (!cand) { ok = false; break }
      cands.set(i, cand)
    }
    if (!ok) continue
    zeroIndex(cands, needs, kinds, n)
    const covers = grid.filter(i => kinds[i] !== 'empty').map(i => cands.get(i)![3])
    const score = (covers.length ? 0.5 * Math.min(...covers) + 0.5 * covers.reduce((s, v) => s + v, 0) / covers.length : 0) - N_PENALTY * Math.abs(n - prefer)
    if (best === null || score > best[0] + EPS) best = [score, n, cands]
  }
  if (!best) return out
  const [, n, cands] = best
  for (const [i, [low, high, step, , zero, why]] of cands) out[i] = { minimum: clean(low), maximum: clean(high), step: clean(step), n, zero, why }
  return out
}

// --- График целиком (зеркало atlas/axis_auto.py) -----------------------------------------------------------------------


const Y_AXES = ['y', 'y2', 'y3', 'y4', 'y5'] as const
type YKey = typeof Y_AXES[number]
const FIELDS = [['minimum', 'min'], ['maximum', 'max'], ['step', 'step']] as const
const MODES: readonly string[] = ['auto', 'zero', 'data']

/** Шкалы Y графика по порядку: 'y' и правые подряд, без пропусков. */
function yNames(chart: Chart): YKey[] {
  const out: YKey[] = ['y']
  for (const name of Y_AXES.slice(1)) { if (!chart[name]) break; out.push(name) }
  return out
}

/** Размах значений шкалы (стопки — суммы) и «нуль обязателен» (столбцы, области, стопки); null — на шкале ящики. */
export function extentOf(chart: Chart, name: string): { lo: number | null; hi: number | null; anchor: boolean } | null {
  let lo = Infinity, hi = -Infinity, anchor = false
  const stacks = new Map<string, number[]>()
  for (const s of chart.series) {
    if ((s.axis ?? 'y') !== name) continue
    if (s.kind === 'box') return null
    anchor = anchor || s.kind === 'bar' || !!s.fill || !!s.stack
    s.y.forEach((v, i) => {
      if (typeof v !== 'number' || !Number.isFinite(v)) return
      if (v < lo) lo = v
      if (v > hi) hi = v
      if (s.stack) {
        const key = s.stack + (v < 0 ? '\u0000-' : '\u0000+')
        const total = stacks.get(key) ?? []
        total[i] = (total[i] ?? 0) + v
        stacks.set(key, total)
      }
    })
  }
  for (const total of stacks.values()) for (const v of total) if (v !== undefined) { if (v < lo) lo = v; if (v > hi) hi = v }
  return lo <= hi ? { lo, hi, anchor } : { lo: null, hi: null, anchor }
}

/** Границы и шаг, заданные вручную или модулем: не равные тому, что подобрал автомат. */
function manualOf(axis: Axis): { minimum: number | null; maximum: number | null; step: number | null } {
  const auto = axis.auto as Record<string, unknown> | null | undefined
  const out = { minimum: null as number | null, maximum: null as number | null, step: null as number | null }
  for (const [attr, key] of FIELDS) {
    const value = attr === 'step' ? axis.step || null : axis[attr]
    out[attr] = value == null || (auto && key in auto && auto[key] === value) ? null : value
  }
  return out
}

/** Шкала без подобранных автоматом границ и шага (заданное вручную или модулем остаётся); сведения подбора сохраняются для
 *  следующего подбора. Оформление оси применяется к такой шкале: подобранный нуль не мешает логарифму, «с нуля» — пересчёту. */
export function unfitted(axis: Axis): Axis {
  return axis.auto ? { ...axis, ...manualOf(axis) } : axis
}

/** Режим шкалы: заданный в оформлении (``style.fit``), иначе «от нуля» по признаку модуля, иначе авто. */
export function fitModeOf(axis: Axis): FitMode {
  const mode = axis.style?.fit
  return mode && MODES.includes(mode) ? mode : axis.from_zero ? 'zero' : 'auto'
}

/** Размах числовой оси X по рядам (как atlas/axis_auto.x_extent); null — ось не подбирается: столбцы и ящики. */
export function xExtentOf(chart: Chart): { lo: number | null; hi: number | null; anchor: boolean } | null {
  let lo = Infinity, hi = -Infinity
  for (const s of chart.series) {
    if (s.kind === 'bar' || s.kind === 'box') return null
    for (const v of s.x) {
      if (typeof v !== 'number' || !Number.isFinite(v)) continue
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
  }
  return lo <= hi ? { lo, hi, anchor: false } : { lo: null, hi: null, anchor: false }
}

/** График с подобранными границами и шагом каждой шкалы Y и числовой оси X (как atlas/axis_auto.auto_chart); без изменений —
 *  тот же объект. Шкалы Y подбираются вместе, ось X — сама по себе.
 *  Размах данных — объединение присланного сервером (полные данные) и видимого на экране (ряды тренда и погрешности). */
export function fitChart(chart: Chart): Chart {
  if (chart.heat) return chart
  const names: (YKey | 'x')[] = [...yNames(chart), 'x']
  const needs = names.map((name): Need | null => {
    const axis = chart[name] as Axis
    const raw = axis.style as Record<string, unknown> | undefined
    if (axis.scale !== 'value' || raw?.min != null || raw?.max != null) return null
    const found = name === 'x' ? xExtentOf(chart) : extentOf(chart, name)
    if (!found) return null
    const known = axis.auto
    const lo = found.lo === null ? known?.lo ?? null : known?.lo != null ? Math.min(found.lo, known.lo) : found.lo
    const hi = found.hi === null ? known?.hi ?? null : known?.hi != null ? Math.max(found.hi, known.hi) : found.hi
    return { lo, hi, anchor: found.anchor, mode: fitModeOf(axis), inverse: !!axis.inverse, ...(name === 'x' ? { margin: 0 } : {}), ...manualOf(axis) }
  })
  if (needs.every(n => !n || n.lo == null) && !names.some(name => (chart[name] as Axis).auto)) return chart
  const fits = [...fitAxes(needs.slice(0, -1)), ...fitAxes(needs.slice(-1))]
  let out = chart
  names.forEach((name, i) => {
    const need = needs[i], axis = chart[name] as Axis
    if (!need && !axis.auto) return
    const fit = need ? fits[i] : null      // шкала перестала подбираться (стала логарифмической): подобранное раньше снимается
    const manual = manualOf(axis)
    let fresh: Axis
    if (!fit || !need) fresh = { ...axis, ...manual, auto: null }
    else {
      const auto = { n: fit.n, zero: fit.zero, why: fit.why, lo: need.lo ?? null, hi: need.hi ?? null, anchor: !!need.anchor } as NonNullable<Axis['auto']>
      if (manual.minimum === null) auto.min = fit.minimum
      if (manual.maximum === null) auto.max = fit.maximum
      if (manual.step === null) auto.step = fit.step
      if (axis.auto?.hints) auto.hints = axis.auto.hints
      fresh = { ...axis, minimum: fit.minimum, maximum: fit.maximum, step: fit.step, auto }
    }
    const same = fresh.minimum === axis.minimum && fresh.maximum === axis.maximum && (fresh.step ?? null) === (axis.step ?? null)
      && JSON.stringify(fresh.auto ?? null) === JSON.stringify(axis.auto ?? null)
    if (!same) out = { ...out, [name]: fresh }
  })
  return out
}

const num = (v: number) => String(clean(v)).replace('.', ',').replace('-', '−')
/** Размах данных в подсказке — до четырёх значащих цифр: «583,3…1086», а не хвост из архива. */
const short = (v: number) => num(Number(v.toPrecision(4)))

/** Строка «почему такие пределы» для панели «Формат»: что подобрано и по какой причине; у ручной шкалы — что задано. */
export function fitHint(axis: Axis | null | undefined, across = false): string {
  if (!axis || axis.scale !== 'value') return ''
  const auto = axis.auto
  if (!auto || axis.minimum == null || axis.maximum == null) return axis.minimum != null || axis.maximum != null ? 'Пределы заданы вручную или разделом: автоподбор их не меняет.' : ''
  const parts = [`Сейчас: ${num(axis.minimum)}…${num(axis.maximum)}`]
  if (axis.step) parts.push(`шаг ${num(axis.step)}`)
  if (auto.n) parts.push(across ? `делений ${auto.n}` : `делений ${auto.n} (одно число на все шкалы графика)`)
  const data = auto.lo != null && auto.hi != null ? ` Данные: ${short(auto.lo)}…${short(auto.hi)}.` : ''
  const why = WHY[auto.why] ?? ''
  return `${parts.join(', ')}.${data}${why ? ` Причина: ${why}.` : ''}`
}

/** Число для поля границы (запятая, как вводит инженер). */
export const boundText = (v: number) => String(clean(v)).replace('.', ',')

/** Подсказка о выбросе: сколько значений и насколько они сжимают остальные данные; пределы предлагаются, решает инженер. */
export function outlierText(h: NonNullable<NonNullable<Axis['auto']>['hints']>[number]): string {
  const shown = h.values.slice(0, 3).map(num).join('; ')
  const what = h.count === 1 ? `значение ${shown}` : `${h.count} значения (${shown}${h.count > 3 ? '…' : ''})`
  return `Выброс: ${what} — остальные данные занимают ${Math.max(1, Math.round(h.share * 100))} % высоты поля. Ничего не отброшено.`
}
