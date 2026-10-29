// Оформление таблицы как в XLSX (atlas/render.py): заливка и цвет шрифта по ячейкам и объединённые ячейки.
// Ключ ячейки — «строка:колонка» (индексы исходной таблицы, не отсортированной).
import type { Table } from './api'

export interface Paint {
  cell: Map<string, { backgroundColor?: string; color?: string }>
  covered: Set<string>                             // ячейки под объединением, кроме левой верхней: не выводятся
  starts: Map<string, { rowSpan: number; colSpan: number }>
}

export function paintOf(table: Table): Paint {
  const keys = table.columns.map(c => c.key)
  const cell: Paint['cell'] = new Map()
  for (const s of table.styles ?? []) {
    const cols = (s.columns.length ? s.columns.map(k => keys.indexOf(k)) : keys.map((_, k) => k)).filter(k => k >= 0)
    for (const r of s.rows) {
      for (const k of cols) {
        const key = r + ':' + k, current = cell.get(key) ?? {}
        if (s.fill) current.backgroundColor = '#' + s.fill
        if (s.font) current.color = '#' + s.font
        cell.set(key, current)
      }
    }
  }
  const covered = new Set<string>(), starts: Paint['starts'] = new Map()
  for (const m of table.merges ?? []) {
    const cols = m.columns.map(k => keys.indexOf(k)).filter(k => k >= 0)
    if (!cols.length) continue
    const first = Math.min(...cols), last = Math.max(...cols)
    starts.set(m.first + ':' + first, { rowSpan: m.last - m.first + 1, colSpan: last - first + 1 })
    for (let r = m.first; r <= m.last; r++) {
      for (let k = first; k <= last; k++) {
        if (r !== m.first || k !== first) covered.add(r + ':' + k)
      }
    }
  }
  return { cell, covered, starts }
}
