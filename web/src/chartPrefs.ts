// Общие настройки вида, запоминаются в браузере: подсказка графиков, события на оси, тема, свёрнутые панели.
import { useSyncExternalStore } from 'react'
import type { HoverMode } from './chartHover'

export interface Pref<T> { get: () => T; set: (next: T) => void; subscribe: (f: () => void) => () => void }

/** Значение в localStorage с подписчиками: меняется в одном месте — обновляются все графики и панели. */
export function pref<T>(key: string, fallback: T, parse: (raw: string) => T = raw => JSON.parse(raw) as T): Pref<T> {
  const listeners = new Set<() => void>()
  let value = fallback
  try { const raw = key ? localStorage.getItem(key) : null; if (raw !== null) value = parse(raw) } catch { /* без хранилища — по умолчанию */ }
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
export const zoomSync = pref<boolean>('atlas.chart.zoomSync', true)

/** Ручные границы шкал Y по графикам (ключ — заголовок и подписи осей): помнятся между запусками. */
export const savedRanges = pref<Record<string, { y: [number, number] | null; y2: [number, number] | null }>>('atlas.chart.ranges', {})
/** Границы Y, разосланные всем графикам раздела с той же подписью и единицей оси (не хранится). */
export const sharedRange = pref<{ key: string; range: [number, number]; n: number } | null>('', null)
