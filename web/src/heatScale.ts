// Цветовые шкалы тепловой карты. Зеркало atlas/heat_scale.py: опорные цвета и правило цвета текста совпадают (проверяет tests/atlas/test_heat_scale.py).
export const HEAT_SCALES = ['orange', 'blue', 'green', 'redgreen', 'gray'] as const
export type HeatScale = typeof HEAT_SCALES[number]
export const HEAT_LABELS: Record<HeatScale, string> = {
  orange: 'Оранжевая', blue: 'Синяя', green: 'Зелёная', redgreen: 'Зелёная к красной', gray: 'Серая (для чёрно-белой печати)',
}
export const STOPS: Record<HeatScale, number[][]> = {
  orange: [[255, 247, 236], [253, 212, 158], [252, 141, 89], [215, 48, 31], [127, 0, 0]],
  blue: [[247, 251, 255], [198, 219, 239], [107, 174, 214], [33, 113, 181], [8, 48, 107]],
  green: [[247, 252, 245], [199, 233, 192], [116, 196, 118], [35, 139, 69], [0, 68, 27]],
  redgreen: [[26, 152, 80], [166, 217, 106], [255, 255, 191], [253, 174, 97], [215, 48, 39]],
  gray: [[255, 255, 255], [217, 217, 217], [150, 150, 150], [82, 82, 82], [0, 0, 0]],
}
export const DARK_LUMA = 150

/** Цвет шкалы в точке t от 0 до 1 (как atlas/heat_scale.py: color). */
export function heatColor(t: number, scheme: HeatScale = 'orange', reverse = false): [number, number, number] {
  const stops = STOPS[scheme] ?? STOPS.orange
  const u = Math.min(1, Math.max(0, t))
  const x = (reverse ? 1 - u : u) * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(x)), f = x - i
  return stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * f)) as [number, number, number]
}

export const isDark = (c: number[]) => 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] < DARK_LUMA
export const rgb = (c: number[]) => `rgb(${c[0]}, ${c[1]}, ${c[2]})`
