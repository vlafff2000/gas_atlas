// Оформление графиков хранится в проекте (settings.chart_formats = {theme, types}, atlas/chart_style.py): одинаково на всех
// компьютерах, в копиях проекта и в выгрузке. Вид рядов — theme.series («Настройка» ряда), оформление графика и осей — theme
// (весь проект) или types[модуль] (графики этого раздела). На экране правка видна сразу, в проект пишется с паузой.
import { useEffect } from 'react'
import { api, type Project } from './api'
import { browserLooks, projectFormats, seriesLooks } from './chartPrefs'
import type { ChartFormat, FormatStore } from './chartFormat'

const SAVE_DELAY = 800                              // мс: перетаскивание ползунка не пишет проект на каждый шаг

const saved = new Map<string, FormatStore>()        // последнее записанное оформление проекта (в этой вкладке): project.settings устаревает

export type FormatScope = 'type' | 'project'

/** Убирает пустое: пустые объекты, пустые строки и неопределённое не хранятся. */
function tidy<T>(value: T): T | undefined {
  if (value === null || value === undefined || value === '') return undefined
  if (Array.isArray(value) || typeof value !== 'object') return value
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(value)) { const t = tidy(v); if (t !== undefined) out[k] = t }
  return Object.keys(out).length ? out as T : undefined
}

/** Что записать в проект: оформление проекта и вид рядов темы. */
const current = (): FormatStore => {
  const store = projectFormats.get(), series = seriesLooks.get()
  return tidy({ ...store, theme: { ...store.theme, series } }) ?? {}
}

/** Документ оформления (график и оси) выбранного уровня: тема проекта или тип графика (id модуля). */
export function formatDoc(store: FormatStore, scope: FormatScope, module: string): ChartFormat {
  const doc = scope === 'project' ? store.theme : store.types?.[module]
  return { chart: doc?.chart, axes: doc?.axes }
}

/** Записывает оформление графика и осей на уровень: на экране сразу, в проект — с паузой. Вид рядов не затрагивается. */
export function setFormatDoc(scope: FormatScope, module: string, doc: ChartFormat) {
  const store = projectFormats.get()
  const part = { chart: doc.chart, axes: doc.axes }
  const next: FormatStore = scope === 'project'
    ? { ...store, theme: { ...store.theme, ...part } }
    : { ...store, types: { ...store.types, [module]: { ...store.types?.[module], ...part } } }
  projectFormats.set(tidy(next) ?? {})
}

/** Подключает оформление открытого проекта: берёт из проекта, правки пишет обратно. Проект без своего оформления
 *  (открыт впервые после обновления) получает вид рядов, который раньше хранился в этом браузере. */
export function useProjectLooks(project: Project | null) {
  const pid = project?.id
  useEffect(() => {
    if (!project) return
    const own = saved.get(project.id) ?? (project.settings.chart_formats as FormatStore | null | undefined) ?? null
    const start = own ?? {}
    projectFormats.set(start)
    seriesLooks.set(own === null ? browserLooks() : start.theme?.series ?? {})
    let sent = JSON.stringify(own === null ? {} : current())
    const remember = () => saved.set(project.id, current())
    let timer: number | undefined
    let busy = false
    const save = () => {
      timer = undefined
      const body = JSON.stringify(current())
      if (busy || body === sent) return
      busy = true
      api.saveSettings(project.id, { chart_formats: JSON.parse(body) })
        .then(() => { sent = body; remember() })
        .catch(e => console.warn('Оформление не сохранено в проекте:', e))
        .finally(() => { busy = false; if (JSON.stringify(current()) !== sent) timer = window.setTimeout(save, SAVE_DELAY) })
    }
    const later = () => { window.clearTimeout(timer); timer = window.setTimeout(save, SAVE_DELAY) }
    const offLooks = seriesLooks.subscribe(later), offFormats = projectFormats.subscribe(later)
    if (own === null && Object.keys(seriesLooks.get()).length) timer = window.setTimeout(save, 0)    // перенос вида из браузера
    return () => {
      offLooks(); offFormats()
      if (timer !== undefined) { window.clearTimeout(timer); save() }     // смена проекта: несохранённое пишется сразу
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])
}
