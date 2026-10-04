// Ручная правка осей графика: зоны осей, масштаб колесом, сдвиг перетаскиванием, ввод границ.
export type AxisName = 'x' | 'y' | 'y2'
export type Range = [number, number]
export interface Rect { x: number; y: number; width: number; height: number }

const BELT = 30      // высота полосы подписей оси X под сеткой, пикселей

/** Какая ось под курсором: подписи слева — Y, справа — вторая шкала, под сеткой — X. */
export function axisAt(px: number, py: number, r: Rect, width: number, hasY2: boolean, hasX: boolean): AxisName | null {
  if (py >= r.y && py <= r.y + r.height) {
    if (px >= 0 && px < r.x) return 'y'
    if (hasY2 && px > r.x + r.width && px <= width) return 'y2'
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
