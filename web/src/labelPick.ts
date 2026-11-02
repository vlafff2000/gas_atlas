// Ручной выбор подписей данных: у каких точек ряда подпись показана (Look.label_pick). Пусто (undefined) — у всех точек.
// Один набор функций для экрана, панели «Формат» и файлов; ключ точки — значение X как его прислала программа (String).
import { useSyncExternalStore } from 'react'
import type { Series } from './api'
import { formatDate } from './format'
import type { Look } from './chartStyle'

/** Ключ точки: целое без «.0», остальное строкой (как pick_key в atlas/engine/core/export.py). */
export const pointKey = (x: unknown): string => (typeof x === 'number' && Number.isInteger(x) ? String(x) : String(x))

/** Подпись точки для списка: даты как дд.мм.гггг. */
export const pointText = (key: string): string => (/^\d{4}-\d{2}-\d{2}/.test(key) ? formatDate(key) : key)

/** Ключи всех точек ряда, у которых есть значение. */
export function pointKeys(s: Series): string[] {
  const out: string[] = []
  s.x.forEach((x, i) => { if (x !== null && s.y[i] !== null && s.y[i] !== undefined) out.push(pointKey(x)) })
  return out
}

/** Щелчок по точке: убирает или возвращает её подпись. Когда подписаны все точки, выбор снимается (undefined). */
export function togglePick(look: Look | undefined, all: string[], key: string): string[] | undefined {
  const now = look?.label_pick ?? all
  const next = now.includes(key) ? now.filter(k => k !== key) : [...now, key]
  return next.length >= all.length ? undefined : next
}

/** Включён ли «выбор щелчком»: пока включён, щелчок по точке графика переключает её подпись (на всех графиках страницы). */
let active = false
const listeners = new Set<() => void>()
export const labelPicker = {
  get: () => active,
  set: (on: boolean) => { active = on; listeners.forEach(f => f()) },
  subscribe: (f: () => void) => { listeners.add(f); return () => { listeners.delete(f) } },
}
export const usePicking = () => useSyncExternalStore(labelPicker.subscribe, labelPicker.get)
