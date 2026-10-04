import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'
import { clickRow, emptyHighlight, moveCursor, selectAll, selectRange, toggleHighlighted } from './listSelection'

interface Props {
  label: string
  options: string[]
  value: string[]
  onChange: (value: string[]) => void
  emptyMeaning?: string      // что значит пустой выбор: «все» или «ничего»
  loading?: boolean
  prefix?: string            // приставка к подписи варианта, например «№ »
}

export function MultiSelect({ label, options, value, onChange, emptyMeaning = 'все', loading, prefix = '' }: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const [highlight, setHighlight] = useState(emptyHighlight)
  const [cursor, setCursor] = useState(0)
  const drag = useRef(false)
  const chosen = useMemo(() => new Set(value), [value])
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? options.filter(o => o.toLowerCase().includes(q)) : options
  }, [options, query])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const release = () => { drag.current = false }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    window.addEventListener('pointerup', release)
    return () => {
      document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc)
      window.removeEventListener('pointerup', release)
    }
  }, [open])
  useEffect(() => { setHighlight(emptyHighlight()); setCursor(0) }, [query, open])
  useEffect(() => { list.current?.children[cursor]?.scrollIntoView({ block: 'nearest' }) }, [cursor])

  const summary = loading ? 'загрузка…'
    : value.length === 0 ? emptyMeaning
    : options.length > 0 && value.length === options.length ? `все (${options.length})`
    : value.length <= 3 ? value.map(v => prefix + v).join(', ')
    : `${value.length} из ${options.length}`

  const toggle = (option: string) => {
    const next = new Set(chosen)
    if (next.has(option)) next.delete(option); else next.add(option)
    onChange(options.filter(o => next.has(o)))       // порядок как в списке
  }
  const setVisible = (on: boolean) => {
    const next = new Set(chosen)
    for (const o of visible) { if (on) next.add(o); else next.delete(o) }
    onChange(options.filter(o => next.has(o)))
  }

  // Выделение строк как в 5.8: мышью (Shift — диапазон, Ctrl — добавить, протяжка), Пробел ставит или снимает флажки всем выделенным.
  const pressRow = (e: ReactPointerEvent, index: number) => {
    if ((e.target as HTMLElement).tagName === 'INPUT' || e.button !== 0) return
    e.preventDefault()
    list.current?.focus()
    setHighlight(h => clickRow(h, visible, index, e.shiftKey, e.ctrlKey || e.metaKey))
    if (!e.shiftKey) setCursor(index)
    drag.current = true
  }
  const enterRow = (index: number) => { if (drag.current) setHighlight(h => selectRange(h, visible, index, false)) }
  const listKey = (e: ReactKeyboardEvent) => {
    if (e.code === 'Space' || e.key === ' ') {
      e.preventDefault()
      onChange(toggleHighlighted(options, value, highlight, visible, cursor))
    } else if ((e.ctrlKey || e.metaKey) && (e.code === 'KeyA' || e.key === 'a' || e.key === 'A')) {
      e.preventDefault()
      setHighlight(selectAll(visible, cursor))
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const moved = moveCursor(highlight, visible, cursor, e.key === 'ArrowDown' ? 1 : -1, e.shiftKey)
      setHighlight(moved.highlight); setCursor(moved.cursor)
    }
  }
  const searchKey = (e: ReactKeyboardEvent) => {
    if (e.key === 'ArrowDown' && visible.length) {
      e.preventDefault()
      list.current?.focus()
      setHighlight({ rows: new Set([visible[0]]), anchor: 0 }); setCursor(0)
    }
  }

  return (
    <div className="multi" ref={root}>
      <button type="button" className="field-button" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="field-label">{label}</span>
        <span className="field-value">{summary}</span>
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label={label}>
          <input autoFocus className="search" placeholder="Найти" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={searchKey} />
          <div className="popover-actions">
            <button type="button" onClick={() => setVisible(true)}>Выбрать {query ? 'найденные' : 'все'}</button>
            <button type="button" onClick={() => setVisible(false)}>Снять {query ? 'найденные' : 'все'}</button>
          </div>
          <ul className="option-list" ref={list} tabIndex={0} role="listbox" aria-multiselectable="true" onKeyDown={listKey}>
            {visible.map((o, i) => (
              <li key={o} role="option" aria-selected={highlight.rows.has(o)}
                className={(highlight.rows.has(o) ? 'highlight' : '') + (i === cursor ? ' cursor' : '')}
                onPointerDown={e => pressRow(e, i)} onPointerEnter={() => enterRow(i)}>
                <input type="checkbox" checked={chosen.has(o)} onChange={() => toggle(o)} aria-label={prefix + o} />
                <span>{prefix}{o}</span>
              </li>
            ))}
            {visible.length === 0 && <li className="muted">Ничего не найдено</li>}
          </ul>
          <p className="popover-foot" title="Выделите строки мышью и нажмите Пробел. Shift — диапазон, Ctrl — добавить, Ctrl+A — все, стрелки — по строкам">{value.length ? `Выбрано ${value.length}` : emptyMeaning === 'все' ? 'Ничего не выбрано — все' : 'Ничего не выбрано'}<span className="popover-hint">Shift/Ctrl — выделить, Пробел — отметить</span></p>
        </div>
      )}
    </div>
  )
}
