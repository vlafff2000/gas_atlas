// Единая модель оформления графика (как в atlas/chart_style.py): документ {chart, axes, series}.
// Уровни (тема проекта → тип графика → график) складываются mergeFormats: поле более позднего уровня главнее.
import type { AxisStyle, ChartStyle } from './api'
import type { Look } from './chartStyle'

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
