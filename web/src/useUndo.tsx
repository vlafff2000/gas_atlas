import { useCallback, useEffect, useReducer, useRef } from 'react'
import { UndoStack, undoKey, type UndoEntry } from './undoStack'
import { Icon } from './Icon'

// Какой из открытых стеков отвечает на Ctrl+Z: последний смонтированный (страница поверх остальных).
const active: symbol[] = []

export interface Undo {
  push: (entry: UndoEntry) => void
  undo: () => Promise<void>
  redo: () => Promise<void>
  canUndo: boolean
  canRedo: boolean
  undoLabel: string
  redoLabel: string
  clear: () => void
  /** сообщение об ошибке отката (показать пользователю) */
  error: string
}

/** Стек отмены страницы. onNotice получает «Отменено: …» после действия. */
export function useUndo(opts: { limit?: number; onNotice?: (text: string) => void; hotkey?: boolean } = {}): Undo {
  const stack = useRef<UndoStack | undefined>(undefined)
  if (!stack.current) stack.current = new UndoStack(opts.limit ?? 50)
  const [, bump] = useReducer((n: number) => n + 1, 0)
  const error = useRef('')
  const notice = useRef(opts.onNotice)
  notice.current = opts.onNotice
  const busy = useRef(false)
  const s = stack.current

  const push = useCallback((entry: UndoEntry) => { s.push(entry); bump() }, [s])
  const run = useCallback(async (kind: 'undo' | 'redo') => {
    if (busy.current) return
    busy.current = true; error.current = ''
    try {
      const label = await (kind === 'undo' ? s.undo() : s.redo())
      if (label) notice.current?.((kind === 'undo' ? 'Отменено: ' : 'Возвращено: ') + label)
    } catch (e) { error.current = (e as Error).message }
    finally { busy.current = false; bump() }
  }, [s])
  const clear = useCallback(() => { s.clear(); bump() }, [s])

  useEffect(() => {
    if (opts.hotkey === false) return
    const id = Symbol('undo')
    active.push(id)
    const onKey = (e: KeyboardEvent) => {
      if (active[active.length - 1] !== id) return
      const kind = undoKey(e)
      if (!kind) return
      if (document.querySelector('[role="dialog"]')) return
      e.preventDefault()
      run(kind)
    }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); active.splice(active.indexOf(id), 1) }
  }, [run, opts.hotkey])

  return {
    push, clear, error: error.current,
    undo: () => run('undo'), redo: () => run('redo'),
    canUndo: s.canUndo, canRedo: s.canRedo, undoLabel: s.undoLabel, redoLabel: s.redoLabel,
  }
}

/**
 * Состояние формы со стеком отмены: каждое изменение, кроме отмены/повтора, записывается снимком «до».
 * Ключ сброса (например, id проекта) очищает историю и не записывает смену значения.
 */
export function useUndoValue<T>(value: T, setValue: (v: T) => void, undo: Undo, label: string, resetKey: string = '') {
  const prev = useRef<T>(value)
  const skip = useRef(true)
  const lastKey = useRef(resetKey)
  useEffect(() => {
    if (lastKey.current !== resetKey) { lastKey.current = resetKey; skip.current = true; undo.clear() }
    const before = prev.current
    prev.current = value
    if (skip.current) { skip.current = false; return }
    if (Object.is(before, value)) return
    undo.push({
      label, key: 'value',
      undo: () => { skip.current = true; setValue(before) },
      redo: () => { skip.current = true; setValue(value) },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, resetKey])
}

/** Кнопки «Отменить» и «Вернуть» в одном виде во всех разделах. */
export function UndoButtons({ undo }: { undo: Undo }) {
  return (
    <span className="undo-buttons" role="group" aria-label="Отмена действий">
      <button type="button" className="quiet small" disabled={!undo.canUndo} onClick={() => undo.undo()}
        title={undo.canUndo ? `Отменить: ${undo.undoLabel} (Ctrl+Z)` : 'Нечего отменять'}><Icon name="undo" /> Отменить</button>
      <button type="button" className="quiet small" disabled={!undo.canRedo} onClick={() => undo.redo()}
        title={undo.canRedo ? `Вернуть: ${undo.redoLabel} (Ctrl+Shift+Z)` : 'Нечего возвращать'}><Icon name="redo" /></button>
      {undo.error && <span className="field-error" role="alert">{undo.error}</span>}
    </span>
  )
}
