// Личный вид рядов графика (окно «Настройка»): цвет, линия, маркеры. Хранится в браузере; данные и расчёт не меняются.
import type { Chart, Series } from './api'

export type MarkerShape = 'circle' | 'square' | 'diamond' | 'triangle' | 'plus' | 'x' | 'star'
export type LineStyleName = 'solid' | 'dash' | 'dot'

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

/** Ключ графика в хранилище: заголовок и подписи осей (как ключ границ Y). */
export const chartLookKey = (chart: Chart) => `${chart.title}|${chart.y.label}|${chart.y2?.label ?? ''}${chart.y3 ? '|' + chart.y3.label : ''}`
/** Ключ ряда внутри графика: группа или имя, и вид ряда. */
export const seriesLookKey = (s: Series) => `${s.group || s.name}|${s.kind}`

/** График с личным видом рядов: у каждого ряда, для которого он задан, появляется поле look. */
export function applyLooks(chart: Chart, looks: Record<string, Look> | undefined): Chart {
  if (!looks || Object.keys(looks).length === 0) return chart
  return { ...chart, series: chart.series.map(s => { const look = looks[seriesLookKey(s)]; return look ? { ...s, look } : s }) }
}
