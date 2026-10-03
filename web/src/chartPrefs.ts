// Общие для всех графиков настройки вида, запоминаются в браузере.
import { useSyncExternalStore } from 'react'
import type { HoverMode } from './chartHover'

const KEY = 'atlas.chart.hover'
const listeners = new Set<() => void>()

function read(): HoverMode {
  try { return localStorage.getItem(KEY) === 'facts' ? 'facts' : 'smooth' } catch { return 'smooth' }
}
let mode: HoverMode = read()

export function setHoverMode(next: HoverMode) {
  mode = next
  try { localStorage.setItem(KEY, next) } catch { /* без хранилища — только до перезагрузки */ }
  listeners.forEach(f => f())
}

export function useHoverMode(): HoverMode {
  return useSyncExternalStore(f => { listeners.add(f); return () => { listeners.delete(f) } }, () => mode)
}
