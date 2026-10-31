// Единая модель оформления графика (как в atlas/chart_style.py): документ {chart, axes, series}.
// Уровни (тема проекта → тип графика → график) складываются mergeFormats: поле более позднего уровня главнее.
import { trendSeries } from './trend'
import type { Axis, AxisStyle, Chart, ChartStyle } from './api'
import { applyLooks, type Look } from './chartStyle'

export type AxisName = 'x' | 'y' | 'y2' | 'y3' | 'y4' | 'y5'
/** Настройки оси: оформление (AxisStyle) + цвет, границы и деления текстом (проверяются на сервере). */
export type AxisFormat = AxisStyle & {
  color?: string; min?: string; max?: string; step?: string; minor_step?: string; cross?: string
  log?: boolean; inverse?: boolean; from_zero?: boolean
}
export interface ChartFormat {
  chart?: ChartStyle
  axes?: Partial<Record<AxisName, AxisFormat>>
  series?: Record<string, Look>      // ключ ряда — seriesLookKey: группа или имя, и вид ряда
}

/** Уровни оформления по порядку: поле более позднего уровня главнее, остальное наследуется. */
export function mergeFormats(...docs: (ChartFormat | null | undefined)[]): ChartFormat {
  const out: ChartFormat = {}
  for (const d of docs) {
    if (!d) continue
    if (d.chart) out.chart = { ...out.chart, ...d.chart }
    for (const [k, v] of Object.entries(d.axes ?? {})) out.axes = { ...out.axes, [k]: { ...out.axes?.[k as AxisName], ...v } }
    for (const [k, v] of Object.entries(d.series ?? {})) out.series = { ...out.series, [k]: { ...out.series?.[k], ...v } }
  }
  return out
}

/** Оформление проекта (settings.chart_formats): тема для всех графиков и свои настройки по типам графиков (id модуля). */
export interface FormatStore { theme?: ChartFormat; types?: Record<string, ChartFormat>; templates?: Record<string, ChartFormat> }

/** Документ для графика модуля: тема проекта → тип графика (как atlas/chart_style.format_of). */
export const formatOf = (store: FormatStore | null | undefined, module?: string): ChartFormat =>
  mergeFormats(store?.theme, module ? store?.types?.[module] : undefined)

const STYLE_KEYS: (keyof AxisStyle)[] = ['decimals', 'date_format', 'font', 'tick_size', 'title_size', 'title_bold', 'title_italic',
  'tick_bold', 'tick_italic', 'ticks', 'minor_ticks', 'line', 'line_color', 'line_width', 'label_rotate', 'units', 'title_place']

/** Граница оси из текста (как chart_style.bound): число с запятой или дата дд.мм.гггг / гггг-мм-дд (мс). Неверное — null. */
export function parseBound(text: string | number | undefined, time: boolean): number | null {
  if (text === undefined || text === null) return null
  const s = String(text).trim()
  if (!s) return null
  if (time) {
    let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
    if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3])
    m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s)
    return m ? Date.UTC(+m[3], +m[2] - 1, +m[1]) : null
  }
  const n = Number(s.replace(/\s/g, '').replace(',', '.'))
  return Number.isFinite(n) ? n : null
}

/** Ось с настройками документа (как chart_style.style_axis): то, что к оси не подходит, пропускается. */
export function formatAxis(axis: Axis, spec: AxisFormat, values: number[]): Axis {
  const time = axis.scale === 'time'
  const out: Axis = { ...axis, style: { ...axis.style } }
  if (spec.color) out.color = spec.color
  for (const k of STYLE_KEYS) if (spec[k] !== undefined) (out.style as Record<string, unknown>)[k] = spec[k]
  if (spec.inverse) out.inverse = true
  if (spec.from_zero && axis.scale === 'value') out.from_zero = true
  const low = parseBound(spec.min, time), high = parseBound(spec.max, time)
  if (low === null || high === null || low < high) {
    if (low !== null) out.minimum = low
    if (high !== null) out.maximum = high
  }
  if (spec.log && !time && values.every(v => v > 0) && (out.minimum === null || out.minimum > 0)) out.scale = 'log'
  if (out.scale === 'value' || out.scale === 'log') {
    const step = parseBound(spec.step, false), minor = parseBound(spec.minor_step, false)
    if (step !== null && step > 0) out.step = step
    if (minor !== null && minor > 0) out.style!.minor_step = minor
  }
  const cross = parseBound(spec.cross, time)
  if (cross !== null) out.style!.cross = cross
  return out
}

const AXES: AxisName[] = ['x', 'y', 'y2', 'y3', 'y4', 'y5']

/** График с оформлением документа (как chart_style.apply_format): стиль графика, оси и вид рядов по ключу ряда.
 *  Данные и расчёт не меняются; оси, которой у графика нет, настройка не создаёт. */
export function applyFormat(chart: Chart, doc: ChartFormat | null | undefined): Chart {
  if (!doc) return chart
  let out: Chart = doc.chart && Object.keys(doc.chart).length ? { ...chart, style: { ...chart.style, ...doc.chart } } : chart
  for (const name of AXES) {
    const spec = doc.axes?.[name], axis = out[name]
    if (!spec || !axis) continue
    const values = name === 'x' ? [] : out.series.filter(s => (s.axis ?? 'y') === name)
      .flatMap(s => s.y.filter((v): v is number => typeof v === 'number' && Number.isFinite(v)))
    out = { ...out, [name]: formatAxis(axis, spec, values) }
  }
  if (!doc.series) return out
  const looked = applyLooks(out, doc.series)
  const trends = trendSeries(looked.series)
  return trends.length ? { ...looked, series: [...looked.series, ...trends] } : looked
}
