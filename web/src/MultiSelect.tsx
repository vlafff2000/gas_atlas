import { useEffect, useMemo, useRef, useState } from 'react'

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
  const chosen = useMemo(() => new Set(value), [value])
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? options.filter(o => o.toLowerCase().includes(q)) : options
  }, [options, query])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])

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

  return (
    <div className="multi" ref={root}>
      <button type="button" className="field-button" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="field-label">{label}</span>
        <span className="field-value">{summary}</span>
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label={label}>
          <input autoFocus className="search" placeholder="Найти" value={query} onChange={e => setQuery(e.target.value)} />
          <div className="popover-actions">
            <button type="button" onClick={() => setVisible(true)}>Выбрать {query ? 'найденные' : 'все'}</button>
            <button type="button" onClick={() => setVisible(false)}>Снять {query ? 'найденные' : 'все'}</button>
          </div>
          <ul className="option-list">
            {visible.map(o => (
              <li key={o}>
                <label><input type="checkbox" checked={chosen.has(o)} onChange={() => toggle(o)} />{prefix}{o}</label>
              </li>
            ))}
            {visible.length === 0 && <li className="muted">Ничего не найдено</li>}
          </ul>
          <p className="popover-foot">{value.length ? `Выбрано ${value.length}` : emptyMeaning === 'все' ? 'Ничего не выбрано — все' : 'Ничего не выбрано'}</p>
        </div>
      )}
    </div>
  )
}
