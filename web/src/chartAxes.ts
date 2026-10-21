import type { Axis, Chart } from './api'
// Ручная правка осей графика: зоны осей, масштаб колесом, сдвиг перетаскиванием, ввод границ.
/** Шкалы Y по порядку: основная слева, затем правые от графика наружу. */
export const Y_NAMES = ['y', 'y2', 'y3', 'y4', 'y5'] as const
export type YName = (typeof Y_NAMES)[number]
export type AxisName = 'x' | YName

/** Правые шкалы графика по порядку от графика наружу (идут подряд, без пропусков). */
export function rightAxes(chart: Chart): Axis[] {
  const out: Axis[] = []
  for (const name of Y_NAMES.slice(1)) {
    const axis = chart[name]
    if (!axis) break
    out.push(axis)
  }
  return out
}

/** Шкалы Y графика: основная и правые. */
export const yAxesOf = (chart: Chart): Axis[] => [chart.y, ...rightAxes(chart)]

/** Номер шкалы Y (0 — основная) для ряда с именем шкалы; ряд на несуществующей шкале уходит на основную. */
export function yIndex(name: string | undefined, yCount: number): number {
  const i = Y_NAMES.indexOf((name ?? 'y') as YName)
  return i > 0 && i < yCount ? i : 0
}

/** Смещение правой шкалы от сетки: вторая и дальше отступают полосой Y_BAND. */
export const rightOffset = (index: number) => Math.max(0, index - 1) * Y_BAND
export type Range = [number, number]
export interface Rect { x: number; y: number; width: number; height: number }

export const Y_BAND = 64      // ширина полосы подписей одной правой оси Y, пикселей
const BELT = 30      // высота полосы подписей оси X под сеткой, пикселей

/** Какая ось под курсором: подписи слева — Y, справа — вторая шкала, под сеткой — X. */
export function axisAt(px: number, py: number, r: Rect, width: number, yCount: number, hasX: boolean): AxisName | null {
  if (py >= r.y && py <= r.y + r.height) {
    if (px >= 0 && px < r.x) return 'y'
    // правые шкалы — полосами Y_BAND одна за другой: полоса считается от правого края сетки
    if (yCount > 1 && px > r.x + r.width && px <= width) return Y_NAMES[Math.min(yCount - 1, Math.ceil((px - r.x - r.width) / Y_BAND))]
  } else if (hasX && px >= r.x && px <= r.x + r.width && py > r.y + r.height && py <= r.y + r.height + BELT) return 'x'
  return null
}

const fwd = (v: number, log: boolean) => (log ? Math.log10(v) : v)
const back = (v: number, log: boolean) => (log ? Math.pow(10, v) : v)

/** Масштаб вокруг значения `at` (его положение на оси не меняется): factor < 1 — приблизить. */
export function zoomRange([lo, hi]: Range, at: number, factor: number, log: boolean): Range | null {
  if (log && (lo <= 0 || hi <= 0 || at <= 0)) return null
  const a = fwd(lo, log), b = fwd(hi, log), c = Math.min(b, Math.max(a, fwd(at, log)))
  const next: Range = [back(c + (a - c) * factor, log), back(c + (b - c) * factor, log)]
  return Number.isFinite(next[0]) && Number.isFinite(next[1]) && next[1] > next[0] ? next : null
}

/** Сдвиг окна на долю его длины (положительная — к большим значениям). */
export function shiftRange([lo, hi]: Range, frac: number, log: boolean): Range | null {
  if (log && (lo <= 0 || hi <= 0)) return null
  const a = fwd(lo, log), b = fwd(hi, log), d = (b - a) * frac
  const next: Range = [back(a + d, log), back(b + d, log)]
  return Number.isFinite(next[0]) && Number.isFinite(next[1]) ? next : null
}

/** Колесо мыши → множитель окна: прокрутка вперёд приближает. */
export const wheelFactor = (deltaY: number) => Math.exp(Math.max(-300, Math.min(300, deltaY)) * 0.0015)

export function formatBound(v: number, time: boolean, span: number): string {
  if (time) {
    const iso = new Date(v).toISOString()
    return span < 3 * 86400e3 ? iso.slice(0, 16).replace('T', ' ') : iso.slice(0, 10)
  }
  const digits = span > 0 ? Math.max(0, 3 - Math.floor(Math.log10(span))) : 2
  return String(Number(v.toFixed(Math.min(10, digits))))
}

/** Граница из текста: число (запятая допустима) или дата `2024-05-17` / `2024-05-17 08:30`. */
export function parseBound(text: string, time: boolean): number | null {
  const s = text.trim()
  if (!s) return null
  if (time) {
    const m = /^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?$/.exec(s)
    if (m) { const t = Date.parse(m[1] + 'T' + (m[2] ?? '00:00') + ':00Z'); return Number.isFinite(t) ? t : null }
    const d = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s)
    if (d) { const t = Date.parse(`${d[3]}-${d[2]}-${d[1]}T00:00:00Z`); return Number.isFinite(t) ? t : null }
    return null
  }
  const n = Number(s.replace(/\s/g, '').replace(',', '.'))
  return Number.isFinite(n) ? n : null
}

const NAME_LABEL_LINES = 3      // строк на название шкалы (единицы — отдельной строкой снизу)

export interface AxisName2 { text: string; lines: number; cut: boolean }

/**
 * Название правой шкалы в полосе width пикселей: название переносится по словам (до трёх строк, дальше «…»),
 * единицы измерения — отдельной строкой, всегда целиком (длинные слова режутся по ширине). Ширина знака — оценка по кеглю.
 */
export function fitAxisName(label: string, unit: string, width: number, fontSize: number): AxisName2 {
  const cap = Math.max(4, Math.floor(width / (fontSize * 0.58)))
  const split = (text: string) => {      // перенос по словам; слово длиннее строки режется
    const out: string[] = []
    let cur = ''
    for (let word of text.split(/\s+/).filter(Boolean)) {
      while (word.length > cap) {
        if (cur) { out.push(cur); cur = '' }
        out.push(word.slice(0, cap)); word = word.slice(cap)
      }
      if (cur && (cur + ' ' + word).length > cap) { out.push(cur); cur = word } else cur = cur ? cur + ' ' + word : word
    }
    if (cur) out.push(cur)
    return out
  }
  let lines = split(label.trim()), cut = false
  if (lines.length > NAME_LABEL_LINES) {
    cut = true
    const rest = lines[NAME_LABEL_LINES - 1]
    lines = lines.slice(0, NAME_LABEL_LINES)
    lines[NAME_LABEL_LINES - 1] = (rest.length >= cap ? rest.slice(0, cap - 1) : rest) + '…'
  }
  const u = unit.trim() ? split(unit.trim()) : []
  const all = [...lines, ...u]
  return { text: all.join('\n'), lines: all.length, cut }
}
