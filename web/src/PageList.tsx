import { useRef, useState } from 'react'

interface Props {
  items: string[]
  checked: string[]
  locked: string[]
  onChange: (checked: string[]) => void
}

/** Список с флажками как обычный список: клик, Shift+клик (диапазон), Ctrl+клик (добавить), стрелки, пробел переключает отмеченные. */
export function PageList({ items, checked, locked, onChange }: Props) {
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [focus, setFocus] = useState(0)
  const anchor = useRef(0)
  const refs = useRef<(HTMLDivElement | null)[]>([])
  const on = (p: string) => locked.includes(p) || checked.includes(p)

  const go = (i: number, shift: boolean, ctrl: boolean) => {
    if (shift) {
      const [a, b] = [Math.min(anchor.current, i), Math.max(anchor.current, i)]
      const range = new Set<number>(); for (let k = a; k <= b; k++) range.add(k)
      setSelected(ctrl ? new Set([...selected, ...range]) : range)
    } else if (ctrl) {
      const next = new Set(selected); if (next.has(i)) next.delete(i); else next.add(i)
      setSelected(next); anchor.current = i
    } else { setSelected(new Set([i])); anchor.current = i }
    setFocus(i); refs.current[i]?.focus()
  }
  const set = (idx: number[], value: boolean) => {
    const names = idx.map(i => items[i]).filter(p => !locked.includes(p))
    onChange(items.filter(p => locked.includes(p) || (names.includes(p) ? value : checked.includes(p))))
  }
  const toggleSelected = () => {
    const idx = selected.size ? [...selected] : [focus]
    const free = idx.filter(i => !locked.includes(items[i]))
    if (free.length) set(free, !free.every(i => on(items[i])))
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); go(Math.max(0, Math.min(items.length - 1, focus + (e.key === 'ArrowDown' ? 1 : -1))), e.shiftKey, false)
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault(); go(e.key === 'Home' ? 0 : items.length - 1, e.shiftKey, false)
    } else if (e.key === ' ') { e.preventDefault(); toggleSelected() }
    else if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A')) { e.preventDefault(); setSelected(new Set(items.keys())) }
  }

  return (
    <div className="page-list" role="listbox" aria-multiselectable="true" aria-label="Разделы меню" onKeyDown={onKey}>
      {items.map((p, i) => (
        <div key={p} ref={el => { refs.current[i] = el }} role="option" aria-selected={selected.has(i)} aria-checked={on(p)}
             tabIndex={i === focus ? 0 : -1} className={'page-item' + (selected.has(i) ? ' selected' : '') + (locked.includes(p) ? ' locked' : '')}
             onClick={e => go(i, e.shiftKey, e.ctrlKey || e.metaKey)}>
          <input type="checkbox" tabIndex={-1} checked={on(p)} disabled={locked.includes(p)} aria-hidden="true"
                 onClick={e => e.stopPropagation()} onChange={e => set([i], e.target.checked)} />
          <span>{p}</span>
        </div>
      ))}
    </div>
  )
}
