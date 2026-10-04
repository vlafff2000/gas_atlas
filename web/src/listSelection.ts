// Выделение строк в списке с флажками, как в 5.8 (app/ui/checklist): щелчок, Shift — диапазон, Ctrl — добавить,
// Ctrl+A — всё, стрелки — по строкам, Пробел — поставить или снять флажки у всех выделенных строк.

export interface Highlight { rows: Set<string>; anchor: number }

export const emptyHighlight = (): Highlight => ({ rows: new Set(), anchor: 0 })

/** Щелчок по строке index видимого списка. */
export function clickRow(h: Highlight, visible: string[], index: number, shift: boolean, ctrl: boolean): Highlight {
  if (shift) return selectRange(h, visible, index, ctrl)
  const rows = ctrl ? new Set(h.rows) : new Set<string>()
  const value = visible[index]
  if (ctrl && h.rows.has(value)) rows.delete(value); else rows.add(value)
  return { rows, anchor: index }
}

/** Диапазон от якоря до index; add — добавить к уже выделенному (Ctrl+Shift). Якорь не двигается. */
export function selectRange(h: Highlight, visible: string[], index: number, add: boolean): Highlight {
  const rows = add ? new Set(h.rows) : new Set<string>()
  const low = Math.min(h.anchor, index), high = Math.max(h.anchor, index)
  for (let i = low; i <= high && i < visible.length; i++) rows.add(visible[i])
  return { rows, anchor: h.anchor }
}

export const selectAll = (visible: string[], anchor: number): Highlight => ({ rows: new Set(visible), anchor })

/** Стрелка вверх или вниз: одна строка, с Shift — расширение диапазона от якоря. */
export function moveCursor(h: Highlight, visible: string[], cursor: number, step: number, shift: boolean): { highlight: Highlight; cursor: number } {
  if (!visible.length) return { highlight: h, cursor: 0 }
  const next = Math.max(0, Math.min(visible.length - 1, cursor + step))
  if (shift) return { highlight: selectRange(h, visible, next, false), cursor: next }
  return { highlight: { rows: new Set([visible[next]]), anchor: next }, cursor: next }
}

/** Пробел: если среди выделенных есть пустой флажок — ставит всем, иначе снимает со всех. Порядок — как в options. */
export function toggleHighlighted(options: string[], checked: string[], h: Highlight, visible: string[], cursor: number): string[] {
  let rows = [...h.rows].filter(v => visible.includes(v))
  if (!rows.length && visible.length) rows = [visible[Math.min(cursor, visible.length - 1)]]
  const next = new Set(checked)
  const enable = rows.some(v => !next.has(v))
  for (const v of rows) { if (enable) next.add(v); else next.delete(v) }
  return options.filter(o => next.has(o))
}
