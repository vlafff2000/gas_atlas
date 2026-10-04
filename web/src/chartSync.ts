// Общее перекрестие: график под курсором сообщает значение X, остальные графики страницы с той же осью
// (даты — все графики по времени; иначе та же подпись и единица) рисуют вертикаль и значения в этой точке.
// Без React: графики подписываются сами и перерисовывают только свой слой.

export interface SyncState { source: number; key: string; x: number }

let current: SyncState | null = null
const listeners = new Set<() => void>()
let counter = 0

/** Номер графика-источника: свой курсор он рисует сам. */
export const nextSyncId = () => ++counter

export function publish(source: number, key: string | null, x: number | null) {
  const next = key === null || x === null || !Number.isFinite(x) ? null : { source, key, x }
  if (!next && current?.source !== source) return          // уход с графика, который не был источником
  if (next && current && current.source === source && current.key === key && current.x === x) return
  current = next
  listeners.forEach(f => f())
}

export const synced = () => current

export function subscribe(f: () => void) {
  listeners.add(f)
  return () => { listeners.delete(f) }
}

// Закреплённые подсказки: закрепив точку на одном графике, она появляется на всех графиках с той же осью X.
// Запись — это положение по X и номер (token); каждый график держит свою карточку и сверяет её с общим списком.
export interface SharedPin { token: number; source: number; key: string; x: number }

let shared: SharedPin[] = []

export const sharedPins = (key: string | null) => (key === null ? [] : shared.filter(p => p.key === key))

export function pinShared(source: number, key: string, x: number, max: number): number {
  const token = ++counter
  shared = [...shared, { token, source, key, x }]
  const same = shared.filter(p => p.key === key)
  if (same.length > max) {
    const drop = new Set(same.slice(0, same.length - max).map(p => p.token))
    shared = shared.filter(p => !drop.has(p.token))
  }
  listeners.forEach(f => f())
  return token
}

export function unpinShared(token: number) {
  if (!shared.some(p => p.token === token)) return
  shared = shared.filter(p => p.token !== token)
  listeners.forEach(f => f())
}

// Общий масштаб по времени: окно оси X (миллисекунды) одного графика повторяют остальные графики по времени.
// null — масштаб сброшен (весь период). Окно живёт в модуле и переживает смену раздела.
export interface ZoomWindow { source: number; from: number; to: number }

let zoom: ZoomWindow | null = null
const zoomListeners = new Set<() => void>()

export const sharedZoom = () => zoom

export function publishZoom(source: number, from: number | null, to: number | null) {
  const next = from === null || to === null || !(to > from) ? null : { source, from, to }
  if (!next && !zoom) return
  if (next && zoom && Math.abs(zoom.from - next.from) <= (next.to - next.from) * 1e-3 && Math.abs(zoom.to - next.to) <= (next.to - next.from) * 1e-3) return
  zoom = next
  zoomListeners.forEach(f => f())
}

export function subscribeZoom(f: () => void) {
  zoomListeners.add(f)
  return () => { zoomListeners.delete(f) }
}
