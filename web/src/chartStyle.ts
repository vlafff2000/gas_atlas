// Вид рядов графика (окно «Настройка»): цвет, линия, маркеры. Хранится в проекте (projectLooks.ts); данные и расчёт не меняются.
import type { Chart, Series } from './api'

export type MarkerShape = 'circle' | 'square' | 'diamond' | 'triangle' | 'plus' | 'x' | 'star'
export type LineStyleName = 'solid' | 'dash' | 'dot' | 'dashdot' | 'longdash'

/** Поля, которые пользователь задал вручную; не заданное берётся по умолчанию из модуля. */
export interface Look {
  color?: string          // цвет линии (для точек — цвет отметок)
  line?: boolean          // линия видна
  width?: number          // толщина линии, px
  dash?: LineStyleName
  marker?: boolean        // отметки видны
  shape?: MarkerShape
  size?: number           // размер отметки, px
  markerColor?: string    // цвет отметок линии, если отличается от линии
  opacity?: number        // прозрачность линии и отметок: 1 — непрозрачно
  valueLabels?: boolean   // подписи значений над столбцами (целые, Times New Roman)
  // модель v2 (atlas/chart_style.py): граница маркера, полый маркер, подписи данных, имя в легенде
  marker_border?: string; marker_border_width?: number; hollow?: boolean
  label_position?: 'top' | 'bottom' | 'left' | 'right' | 'inside' | 'center'; label_decimals?: number; label_size?: number
  legend_name?: string
  // линия тренда ряда (web/src/trend.ts, atlas/trend.py)
  trend?: 'linear' | 'poly' | 'log' | 'power' | 'exp' | 'moving'; trend_order?: number; trend_period?: number
  trend_label?: boolean; trend_color?: string; trend_width?: number
  // штриховка столбцов для чёрно-белой печати
  // погрешность (доверительный интервал): в процентах или абсолютная, усы или граничные линии
  err_mode?: 'percent' | 'abs'; err_value?: number; err_style?: 'bars' | 'band'
  hatch?: 'diag' | 'back' | 'cross' | 'grid' | 'dots' | 'horizontal' | 'vertical'; hatch_color?: string
}

export const MARKER_SHAPES: { value: MarkerShape; label: string }[] = [
  { value: 'circle', label: 'Круг' },
  { value: 'square', label: 'Квадрат' },
  { value: 'diamond', label: 'Ромб' },
  { value: 'triangle', label: 'Треугольник' },
  { value: 'plus', label: 'Крест (+)' },
  { value: 'x', label: 'Крест (×)' },
  { value: 'star', label: 'Звезда' },
]

export const LINE_STYLES: { value: LineStyleName; label: string }[] = [
  { value: 'solid', label: 'Сплошная' },
  { value: 'dash', label: 'Штриховая' },
  { value: 'dot', label: 'Пунктирная' },
  { value: 'dashdot', label: 'Штрихпунктирная' },
  { value: 'longdash', label: 'Длинный штрих' },
]

// Крест и звезда — контуры в условных координатах [-1, 1]; ECharts растягивает их до размера отметки.
const PLUS = 'path://M-0.3,-1 L0.3,-1 L0.3,-0.3 L1,-0.3 L1,0.3 L0.3,0.3 L0.3,1 L-0.3,1 L-0.3,0.3 L-1,0.3 L-1,-0.3 L-0.3,-0.3 Z'
const X = 'path://M-1,-0.7 L-0.7,-1 L0,-0.3 L0.7,-1 L1,-0.7 L0.3,0 L1,0.7 L0.7,1 L0,0.3 L-0.7,1 L-1,0.7 L-0.3,0 Z'
const STAR = (() => {
  const pts: string[] = []
  for (let i = 0; i < 10; i++) {
    const r = i % 2 ? 0.45 : 1, a = -Math.PI / 2 + (i * Math.PI) / 5
    pts.push(`${(r * Math.cos(a)).toFixed(3)},${(r * Math.sin(a)).toFixed(3)}`)
  }
  return 'path://M' + pts.join(' L') + ' Z'
})()
const SYMBOLS: Record<MarkerShape, string> = { circle: 'circle', square: 'rect', diamond: 'diamond', triangle: 'triangle', plus: PLUS, x: X, star: STAR }

/** Символ ECharts для выбранной формы; без выбора — форма из модуля. */
export const markerSymbol = (shape: MarkerShape | undefined, fallback: string) => (shape ? SYMBOLS[shape] : fallback)

/** Ключ ряда в общем хранилище: группа или имя, и вид ряда. Не зависит от графика, заголовка и набора скважин:
 *  один и тот же год, сезон или группа получает один и тот же вид на всех графиках. */
export const seriesLookKey = (s: Series) => `${s.group || s.name}|${s.kind}`

/** Год, по которому ряд узнаётся как год или сезон («2024», «2023/2024», «Сезон 2024»): цвет по умолчанию не зависит от набора рядов. */
export const yearOfKey = (key: string): number | null => {
  const m = /(?:^|\D)((?:19|20)\d{2})(?!\d)/.exec(key)
  return m ? Number(m[1]) : null
}

/** Личный вид, относящийся к рядам этого графика: из общего хранилища берутся только его ключи. */
export function looksOf(chart: Chart, all: Record<string, Look>): Record<string, Look> {
  return Object.fromEntries(chart.series.map(seriesLookKey).filter(k => all[k]).map(k => [k, all[k]]))
}

/** График с личным видом рядов: у каждого ряда, для которого он задан, появляется поле look. */
export function applyLooks(chart: Chart, looks: Record<string, Look> | undefined): Chart {
  if (!looks || Object.keys(looks).length === 0) return chart
  const series = chart.series.map(s => {
    const own = looks[seriesLookKey(s)]
    if (!own) return s
    const look = { ...s.look, ...own }      // вид из макета (конструктор) дополняется личным видом браузера
    return { ...s, look, ...(look.opacity !== undefined ? { opacity: look.opacity } : {}) }
  })
  // цвет правой шкалы следует за цветом её рядов: когда у всех рядов шкалы задан один цвет, шкала берёт его
  const out: Chart = { ...chart, series }
  for (const name of ['y2', 'y3', 'y4', 'y5'] as const) {
    const axis = chart[name]
    if (!axis?.color) continue
    const mine = series.filter(s => (s.axis ?? 'y') === name)
    const colors = new Set(mine.map(s => s.look?.color))
    const only = colors.size === 1 ? [...colors][0] : undefined
    if (only) out[name] = { ...axis, color: only }
  }
  return out
}
