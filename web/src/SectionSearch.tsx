import { useEffect, useMemo, useRef, useState } from 'react'

export interface Section { id: string; title: string; group: string; hint?: string }

/** Без учёта регистра и буквы «ё»; слова запроса ищутся в начале слов названия или группы. */
const norm = (s: string) => s.toLowerCase().replace(/ё/g, 'е')
function score(section: Section, query: string): number {
  const words = norm(query).split(/\s+/).filter(Boolean)
  if (!words.length) return 1
  const title = norm(section.title), all = title + ' ' + norm(section.group) + ' ' + norm(section.hint ?? '')
  let total = 0
  for (const w of words) {
    if (title.startsWith(w)) total += 4
    else if (new RegExp('(^|[\\s«(/-])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).test(all)) total += 2
    else if (all.includes(w)) total += 1
    else return 0
  }
  return total
}

interface Props { sections: Section[]; open: boolean; onClose: () => void; onGo: (id: string) => void }

/** Быстрый переход к разделу: Ctrl+K, ввод нескольких букв, стрелки и Enter. */
export function SectionSearch({ sections, open, onClose, onGo }: Props) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const found = useMemo(() => sections.map(s => ({ s, k: score(s, query) })).filter(r => r.k > 0)
    .sort((a, b) => b.k - a.k).map(r => r.s), [sections, query])
  useEffect(() => { if (open) { setQuery(''); setActive(0); setTimeout(() => input.current?.focus(), 0) } }, [open])
  useEffect(() => { setActive(0) }, [query])
  if (!open) return null
  const go = (s: Section | undefined) => { if (s) { onGo(s.id); onClose() } }
  return (
    <div className="palette-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Переход к разделу">
        <input ref={input} className="palette-input" value={query} placeholder="Раздел: например, «реаг» или «гди»"
          role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={found[active] ? 'palette-' + active : undefined}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(found.length - 1, a + 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(0, a - 1)) }
            else if (e.key === 'Enter') { e.preventDefault(); go(found[active]) }
            else if (e.key === 'Escape') { e.preventDefault(); onClose() }
          }} />
        <ul id="palette-list" role="listbox" className="palette-list">
          {found.map((s, i) => (
            <li key={s.id} id={'palette-' + i} role="option" aria-selected={i === active}
              onMouseEnter={() => setActive(i)} onMouseDown={e => { e.preventDefault(); go(s) }}>
              <span>{s.title}</span><small>{s.group}</small>
            </li>
          ))}
          {!found.length && <li className="palette-empty">Нет такого раздела</li>}
        </ul>
        <p className="palette-foot"><kbd>↑</kbd> <kbd>↓</kbd> выбор · <kbd>Enter</kbd> открыть · <kbd>Esc</kbd> закрыть</p>
      </div>
    </div>
  )
}
