import { useEffect } from 'react'
import { SHORTCUTS } from './shortcuts'
import './menuwindow.css'

/** Окно «Сочетания клавиш» (в том же виде, что остальные окна: затемнение, заголовок, закрытие по Esc). */
export function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const groups = [...new Set(SHORTCUTS.map(s => s.group))]
  return (
    <div className="palette-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="menu-window" role="dialog" aria-modal="true" aria-label="Сочетания клавиш">
        <header className="menu-window-head">
          <h2>Сочетания клавиш</h2>
          <button type="button" className="menu-close" onClick={onClose} aria-label="Закрыть" title="Закрыть (Esc)">×</button>
        </header>
        <div className="menu-groups">
          {groups.map(g => (
            <section key={g} className="menu-group">
              <h3 className="menu-note">{g}</h3>
              <dl className="shortcut-list">
                {SHORTCUTS.filter(s => s.group === g).map(s => (
                  <div key={s.keys}><dt><kbd>{s.keys}</kbd></dt><dd>{s.text}</dd></div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
