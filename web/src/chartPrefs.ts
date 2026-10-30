// Общие настройки вида, запоминаются в браузере: подсказка графиков, события на оси, тема, свёрнутые панели.
import { useSyncExternalStore } from 'react'
import type { HoverMode } from './chartHover'
import type { Look } from './chartStyle'

export interface Pref<T> { get: () => T; set: (next: T) => void; subscribe: (f: () => void) => () => void }

/** Размеры панелей и свёрнутость меню у каждого окна свои; остальные настройки подхватываются из второго окна. */
const PER_WINDOW = /(sidebar\.collapsed|layersBox|inspector)$/

/** Значение в localStorage с подписчиками: меняется в одном месте — обновляются все графики и панели. */
export function pref<T>(key: string, fallback: T, parse: (raw: string) => T = raw => JSON.parse(raw) as T): Pref<T> {
  const listeners = new Set<() => void>()
  let value = fallback
  try { const raw = key ? localStorage.getItem(key) : null; if (raw !== null) value = parse(raw) } catch { /* без хранилища — по умолчанию */ }
  if (key && !PER_WINDOW.test(key)) {
    try {
      window.addEventListener('storage', e => {
        if (e.key !== key || e.storageArea !== localStorage || e.newValue === null) return
        try {
          const next = parse(e.newValue)
          if (JSON.stringify(next) === JSON.stringify(value)) return
          value = next
          listeners.forEach(f => f())
        } catch { /* повреждённое значение */ }
      })
    } catch { /* нет window */ }
  }
  return {
    get: () => value,
    set: next => {
      value = next
      try { if (key) localStorage.setItem(key, typeof next === 'string' ? next : JSON.stringify(next)) } catch { /* только до перезагрузки */ }
      listeners.forEach(f => f())
    },
    subscribe: f => { listeners.add(f); return () => { listeners.delete(f) } },
  }
}

export function usePref<T>(p: Pref<T>): T {
  return useSyncExternalStore(p.subscribe, p.get)
}

export const hoverMode = pref<HoverMode>('atlas.chart.hover', 'smooth', raw => (raw === 'facts' ? 'facts' : 'smooth'))
export const setHoverMode = (next: HoverMode) => hoverMode.set(next)
export const useHoverMode = () => usePref(hoverMode)

/** Прореживание линий на экране (М4 на сервере, LTTB в ECharts). Выключено — все точки: графики целостнее, но на больших данных медленнее. */
export const thinCharts = pref<boolean>('atlas.chart.thin', true, raw => raw !== 'false')

/** Сплошная кривая: плотные ряды замеров (давление, уровень) рисуются сглаженной линией — среднее по подряд идущим замерам. */
export const smoothLines = pref<boolean>('atlas.chart.smooth', false, raw => raw === 'true')

/** Графиков в ряду: 0 — подбирается по ширине, 1–3 — задано вручную (плитка по скважинам). */
export const chartColumns = pref<number>('atlas.chart.columns', 0, raw => { const n = Number(raw); return n >= 1 && n <= 3 ? n : 0 })

/** Виды событий, скрытые на всех графиках (щелчок по пункту «События» в легенде). */
export const hiddenEvents = pref<string[]>('atlas.chart.hiddenEvents', [])

export type Theme = 'light' | 'dark' | 'system'
export const theme = pref<Theme>('atlas.theme', 'light', raw => (raw === 'dark' || raw === 'light' ? raw : 'system'))

/** Тема на экране сейчас: «как в системе» раскрывается по настройке ОС. */
const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
export function resolvedTheme(): 'light' | 'dark' {
  const t = theme.get()
  return t === 'system' ? (media?.matches ? 'dark' : 'light') : t
}
const applied = pref<'light' | 'dark'>('', resolvedTheme())     // без ключа: не хранится
function apply() {
  const t = resolvedTheme()
  document.documentElement.dataset.theme = t
  document.documentElement.style.colorScheme = t
  if (applied.get() !== t) applied.set(t)
}
if (typeof document !== 'undefined') {
  apply()
  theme.subscribe(apply)
  media?.addEventListener?.('change', apply)
}
/** Тема, которой сейчас нарисован экран: графики перечитывают цвета при её смене. */
export const useAppliedTheme = () => usePref(applied)

export const sidebarCollapsed = pref<boolean>('atlas.sidebar.collapsed', false)
export const paramsCollapsed = pref<boolean>('atlas.params.collapsed', false)
export const tableBars = pref<boolean>('atlas.table.bars', true)

/** Общий масштаб по времени: прокрутка бегунка на одном графике двигает все графики по времени. */
/** Связь таблицы с графиками по времени: курсор на графике подсвечивает строку, наведение на строку ставит курсор на графики. */
export const tableSync = pref<boolean>('atlas.table.sync', true, raw => raw !== 'false')

export const zoomSync = pref<boolean>('atlas.chart.zoomSync', true)

/** Ручные границы шкал Y по графикам (ключ — заголовок и подписи осей): помнятся между запусками. */
export const savedRanges = pref<Record<string, Partial<Record<'y' | 'y2' | 'y3' | 'y4' | 'y5', [number, number] | null>>>>('atlas.chart.ranges', {})
/** Основной интервал делений осей по графикам (ключ как у savedRanges): ось → шаг. */
export const savedSteps = pref<Record<string, Partial<Record<'x' | 'y' | 'y2' | 'y3' | 'y4' | 'y5', { n: number; unit: 'num' | 'year' | 'month' | 'week' | 'day' }>>>>('atlas.chart.steps', {})
/** Личный вид рядов («Настройка») — общий для всех графиков: ключ ряда (группа или имя и вид) → вид. Помнится между запусками.
 *  Раньше вид хранился по графикам (ключ — заголовок), поэтому смена набора скважин его теряла: при первом запуске переносится. */
export const seriesLooks = pref<Record<string, Look>>('atlas.series.looks', legacyLooks())
function legacyLooks(): Record<string, Look> {
  try {
    if (localStorage.getItem('atlas.series.looks') !== null) return {}
    const old = JSON.parse(localStorage.getItem('atlas.chart.looks') ?? '{}') as Record<string, Record<string, Look>>
    return Object.assign({}, ...Object.values(old))
  } catch { return {} }
}
/** Границы Y, разосланные всем графикам раздела с той же подписью и единицей оси (не хранится). */
export const sharedRange = pref<{ key: string; range: [number, number]; n: number } | null>('', null)

/** Синхронизация закреплённых точек между графиками — отдельно от перекрестия. По времени полезна (по умолчанию включена),
 *  у остальных графиков (ГДИ и др.) выключена. */
export const pinSync = pref<{ time: boolean; other: boolean }>('atlas.chart.pinSync', { time: true, other: false },
  raw => { const v = JSON.parse(raw); return { time: v?.time !== false, other: v?.other === true } })
export const pinSyncKind = (chart: { x: { scale: string } }): 'time' | 'other' => (chart.x.scale === 'time' ? 'time' : 'other')
