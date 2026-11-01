/** Общий стек отмены (без React): снимки значения и действия с обратным ходом. Копия лежит в all_scripts/pxg_core/web-ui. */

export interface UndoEntry {
  label: string
  /** вернуть состояние «до»; может быть асинхронным (например, откат на сервере) */
  undo: () => void | Promise<void>
  /** повторить отменённое */
  redo?: () => void | Promise<void>
  /** записи с одним ключом, пришедшие подряд за короткое время, склеиваются (набор текста, перетаскивание) */
  key?: string
  at?: number
}

export class UndoStack {
  private past: UndoEntry[] = []
  private future: UndoEntry[] = []
  private limit: number
  private coalesceMs: number
  constructor(limit = 50, coalesceMs = 700) { this.limit = limit; this.coalesceMs = coalesceMs }

  get canUndo() { return this.past.length > 0 }
  get canRedo() { return this.future.length > 0 }
  get undoLabel() { return this.past[this.past.length - 1]?.label ?? '' }
  get redoLabel() { return this.future[this.future.length - 1]?.label ?? '' }
  get size() { return this.past.length }

  push(entry: UndoEntry, now = Date.now()) {
    const last = this.past[this.past.length - 1]
    if (last && entry.key && last.key === entry.key && now - (last.at ?? 0) < this.coalesceMs) {
      // сохраняем исходное «до» первой записи, а повтор берём от последней
      this.past[this.past.length - 1] = { ...last, redo: entry.redo, label: entry.label, at: now }
    } else {
      this.past.push({ ...entry, at: now })
      if (this.past.length > this.limit) this.past.shift()
    }
    this.future = []
  }

  async undo(): Promise<string | null> {
    const entry = this.past.pop()
    if (!entry) return null
    try { await entry.undo() } catch (e) { this.past.push(entry); throw e }
    this.future.push(entry)
    return entry.label
  }

  async redo(): Promise<string | null> {
    const entry = this.future.pop()
    if (!entry || !entry.redo) { return null }
    try { await entry.redo() } catch (e) { this.future.push(entry); throw e }
    this.past.push(entry)
    return entry.label
  }

  clear() { this.past = []; this.future = [] }
}

/** Ctrl+Z / Cmd+Z — отмена, Ctrl+Shift+Z и Ctrl+Y — повтор. В полях ввода работает встроенная отмена текста. */
export function undoKey(e: { key: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean; target?: unknown }): 'undo' | 'redo' | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return null
  const t = e.target as { tagName?: string; isContentEditable?: boolean; type?: string } | null | undefined
  const tag = (t?.tagName ?? '').toUpperCase()
  if (tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable) return null
  if (tag === 'INPUT' && !['checkbox', 'radio', 'button', 'range'].includes((t?.type ?? '').toLowerCase())) return null
  const k = e.key.toLowerCase()
  if (k === 'z') return e.shiftKey ? 'redo' : 'undo'
  if (k === 'y' && !e.shiftKey) return 'redo'
  return null
}
