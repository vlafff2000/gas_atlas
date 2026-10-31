// Вид рядов из окна «Настройка» хранится в проекте (тема оформления: settings.chart_formats.theme.series, atlas/chart_style.py):
// одинаков на всех компьютерах, в копиях проекта и в выгрузке. На экране он применяется сразу, в проект пишется с паузой.
import { useEffect } from 'react'
import { api, type Project } from './api'
import { browserLooks, projectFormats, seriesLooks } from './chartPrefs'
import type { ChartFormat, FormatStore } from './chartFormat'
import type { Look } from './chartStyle'

const SAVE_DELAY = 800                              // мс: перетаскивание ползунка толщины не пишет проект на каждый шаг
const saved = new Map<string, FormatStore>()        // последнее записанное оформление проекта (в этой вкладке)

/** Тема с новым видом рядов: пустые части не хранятся. */
function withSeries(store: FormatStore, series: Record<string, Look>): FormatStore {
  const theme: ChartFormat = { ...store.theme, series }
  if (!Object.keys(series).length) delete theme.series
  const next: FormatStore = { ...store, theme }
  if (!Object.keys(theme).length) delete next.theme
  return next
}

/** Подключает вид рядов открытого проекта: берёт его из проекта, правки пишет обратно. Проект без своего оформления
 *  (открыт впервые после обновления) получает вид, который раньше хранился в этом браузере. */
export function useProjectLooks(project: Project | null) {
  const pid = project?.id
  useEffect(() => {
    if (!project) return
    const own = saved.get(project.id) ?? (project.settings.chart_formats as FormatStore | null | undefined) ?? null
    let store: FormatStore = own ?? {}
    let written = JSON.stringify(store.theme?.series ?? {})
    const start = own === null ? browserLooks() : store.theme?.series ?? {}
    seriesLooks.set(start)
    projectFormats.set(store)
    let timer: number | undefined
    let busy = false
    const save = () => {
      timer = undefined
      const series = seriesLooks.get()
      if (busy || JSON.stringify(series) === written) return
      busy = true
      const next = withSeries(store, series)
      api.saveSettings(project.id, { chart_formats: next })
        .then(p => {
          store = (p.settings.chart_formats ?? {}) as FormatStore
          saved.set(project.id, store)
          projectFormats.set(store)
          written = JSON.stringify(store.theme?.series ?? {})
        })
        .catch(e => console.warn('Вид рядов не сохранён в проекте:', e))
        .finally(() => { busy = false; if (JSON.stringify(seriesLooks.get()) !== written) timer = window.setTimeout(save, SAVE_DELAY) })
    }
    const off = seriesLooks.subscribe(() => { window.clearTimeout(timer); timer = window.setTimeout(save, SAVE_DELAY) })
    if (own === null && Object.keys(start).length) timer = window.setTimeout(save, 0)    // перенос вида из браузера
    return () => {
      off()
      if (timer !== undefined) { window.clearTimeout(timer); save() }     // смена проекта: несохранённое пишется сразу
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])
}
