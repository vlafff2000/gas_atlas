// Единая область таблиц модуля: кнопки с названиями, как у графиков; можно показать две таблицы рядом или друг под другом.
// Невидимые таблицы остаются смонтированными (правки и отметки не теряются), а ещё не открывавшиеся не создаются — большие подгружаются при первом показе.
import { useEffect, useState, type ReactNode } from 'react'
import type { Table } from './api'

export type TableLayout = 'one' | 'cols' | 'rows'
interface Saved { sel: string[]; layout: TableLayout }

const LAYOUTS: { id: TableLayout; label: string; hint: string }[] = [
  { id: 'one', label: 'Одна', hint: 'Показать одну таблицу' },
  { id: 'cols', label: 'Рядом', hint: 'Две таблицы рядом' },
  { id: 'rows', label: 'Друг под другом', hint: 'Две таблицы одна под другой' },
]
const key = (scope: string) => `atlas:tables:${scope}`

function load(scope: string): Saved {
  try {
    const v = JSON.parse(localStorage.getItem(key(scope)) ?? 'null')
    if (v && Array.isArray(v.sel) && LAYOUTS.some(l => l.id === v.layout)) return { sel: v.sel.map(String).slice(0, 2), layout: v.layout }
  } catch { /* без памяти */ }
  return { sel: [], layout: 'one' }
}

interface Props {
  tables: Table[]
  scope: string                                  // модуль/страница: выбор запоминается отдельно
  render: (table: Table) => ReactNode
}

export function TableDock({ tables, scope, render }: Props) {
  const [saved, setSaved] = useState<Saved>(() => load(scope))
  useEffect(() => { setSaved(load(scope)) }, [scope])
  const ids = tables.map(t => t.id)
  // сохранённые названия могли исчезнуть (другие параметры расчёта): тогда первая таблица
  const alive = saved.sel.filter(id => ids.includes(id))
  const sel = alive.length ? alive : ids.slice(0, 1)
  const visible = saved.layout === 'one' ? sel.slice(0, 1) : sel
  const [opened, setOpened] = useState<string[]>([])
  const shown = visible.join('|')
  useEffect(() => { setOpened(o => [...new Set([...o, ...shown.split('|').filter(Boolean)])]) }, [shown])
  useEffect(() => { setOpened([]) }, [scope])

  if (tables.length === 0) return null
  const commit = (next: Saved) => {
    setSaved(next)
    try { localStorage.setItem(key(scope), JSON.stringify(next)) } catch { /* только до перезагрузки */ }
  }
  const pick = (id: string, add: boolean) => {
    if (saved.layout === 'one' && !add) return commit({ sel: [id], layout: 'one' })
    if (visible.includes(id)) {
      if (visible.length > 1) commit({ ...saved, sel: visible.filter(x => x !== id) })
    } else if (saved.layout === 'one') {
      commit({ sel: [visible[0], id], layout: 'cols' })
    } else {
      commit({ ...saved, sel: [...visible, id].slice(-2) })
    }
  }
  const setLayout = (layout: TableLayout) => {
    if (layout === 'one') return commit({ sel: sel.slice(0, 1), layout })
    const second = sel.length > 1 ? sel[1] : ids.find(id => id !== sel[0])
    commit({ sel: second ? [sel[0], second] : sel, layout })
  }

  return (
    <section className="table-dock" aria-label="Таблицы">
      {tables.length > 1 && (
        <div className="dock-bar">
          <div className="dock-tabs" role="group" aria-label="Таблицы модуля">
            {tables.map(t => (
              <button key={t.id} type="button" className={'dock-tab' + (visible.includes(t.id) ? ' on' : '')}
                aria-pressed={visible.includes(t.id)}
                title="Щелчок — показать таблицу; Ctrl или Shift + щелчок — добавить или убрать вторую"
                onClick={e => pick(t.id, e.ctrlKey || e.shiftKey || e.metaKey)}>
                {t.title}<span className="muted"> {t.count}</span>
              </button>
            ))}
          </div>
          <div className="dock-layout" role="group" aria-label="Раскладка таблиц">
            {LAYOUTS.map(l => (
              <button key={l.id} type="button" className={'quiet small' + (saved.layout === l.id ? ' on' : '')}
                aria-pressed={saved.layout === l.id} title={l.hint} onClick={() => setLayout(l.id)}>{l.label}</button>
            ))}
          </div>
        </div>
      )}
      <div className={'dock-body dock-' + (visible.length > 1 ? saved.layout : 'one')}>
        {tables.filter(t => opened.includes(t.id) || visible.includes(t.id)).map(t => (
          <div key={t.id} className="dock-item" hidden={!visible.includes(t.id)}>{render(t)}</div>
        ))}
      </div>
    </section>
  )
}
