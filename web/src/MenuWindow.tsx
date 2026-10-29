import { useEffect, useState } from 'react'
import type { ModuleSpec, Project } from './api'
import { alwaysInMenu, hiddenPages, PROJECT_PAGES } from './api_projects'
import { menuPrefs, PAGES_GROUP } from './menuPrefs'
import { usePref } from './chartPrefs'
import './menuwindow.css'

interface Entry { id: string; title: string; locked: boolean }
interface Section { title: string; entries: Entry[] }

interface Props {
  groups: [string, ModuleSpec[]][]
  project: Project | null
  onClose: () => void
}

/** Окно «Разделы меню»: большие группы боковой панели, в каждой — свои разделы и модули с флажками. */
export function MenuWindow({ groups, project, onClose }: Props) {
  const menu = usePref(menuPrefs)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const hidden = hiddenPages(project)
  const hiddenGroups = new Set(menu?.groups ?? [])

  const sections: Section[] = [
    ...groups.map(([title, items]) => ({ title, entries: items.map(m => ({ id: m.id, title: m.title, locked: alwaysInMenu(m.id) })) })),
    { title: PAGES_GROUP, entries: PROJECT_PAGES.map(p => ({ id: p.id, title: p.title, locked: alwaysInMenu(p.id) })) },
  ]

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const save = (nextHidden: Set<string>, nextGroups: Set<string>) => menuPrefs.set({ hidden: [...nextHidden], groups: [...nextGroups] })
  const toggle = (set: Set<string>, key: string) => { const next = new Set(set); if (next.has(key)) next.delete(key); else next.add(key); return next }
  const toggleItem = (id: string) => save(toggle(hidden, id), hiddenGroups)
  const toggleGroup = (title: string) => save(hidden, toggle(hiddenGroups, title))
  const toggleOpen = (title: string) => setOpen(s => toggle(s, title))
  const showAll = () => save(new Set(), new Set())

  return (
    <div className="palette-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="menu-window" role="dialog" aria-modal="true" aria-label="Разделы меню">
        <header className="menu-window-head">
          <h2>Разделы меню</h2>
          <button type="button" className="quiet" onClick={showAll}>Показать всё</button>
          <button type="button" className="menu-close" onClick={onClose} aria-label="Закрыть" title="Закрыть (Esc)">×</button>
        </header>
        <p className="muted small-text menu-note">Выбор запоминается на этом компьютере и одинаков для всех объектов.
          Галочка у группы прячет её целиком. «Данные» и «Настройки» видны всегда.</p>
        <div className="menu-groups">
          {sections.map(sec => {
            const groupOff = hiddenGroups.has(sec.title)
            const isOpen = open.has(sec.title)
            const shown = sec.entries.filter(e => e.locked || !hidden.has(e.id)).length
            return (
              <section key={sec.title} className={'menu-group' + (groupOff ? ' off' : '')}>
                <div className="menu-group-head">
                  <button type="button" className="menu-expand" aria-expanded={isOpen} aria-label={isOpen ? 'Свернуть' : 'Раскрыть'}
                          onClick={() => toggleOpen(sec.title)}>
                    <svg viewBox="0 0 16 16" aria-hidden="true"><path d={isOpen ? 'M3.5 6 8 10.5 12.5 6' : 'M6 3.5 10.5 8 6 12.5'} /></svg>
                  </button>
                  <label className="menu-group-name">
                    <input type="checkbox" checked={!groupOff} onChange={() => toggleGroup(sec.title)} />
                    <span>{sec.title}</span>
                  </label>
                  <small className="muted">{shown} из {sec.entries.length}</small>
                </div>
                {isOpen && (
                  <ul className="menu-items">
                    {sec.entries.map(e => (
                      <li key={e.id}>
                        <label>
                          <input type="checkbox" checked={e.locked || !hidden.has(e.id)} disabled={e.locked} onChange={() => toggleItem(e.id)} />
                          <span>{e.title}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )
          })}
        </div>
      </div>
    </div>
  )
}
