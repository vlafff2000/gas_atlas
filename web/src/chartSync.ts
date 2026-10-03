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
