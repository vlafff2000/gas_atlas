// Окно «Цвета групп»: выбор цвета каждой группы вручную, запоминание (общее для всех программ), сброс на палитру.
// Решение за инженером: цвет, выбранный вручную, всегда главнее палитры. Подключение: <GroupColorsButton groups={...} />, цвета на графиках
// пересчитываются подпиской onGroupColorsChange (или onChange у кнопки).
import { useEffect, useRef, useState } from 'react'
import { groupColors, hasGroupColorOverride, loadGroupColorOverrides, onGroupColorsChange, saveGroupColor } from './groupColors'
import './groupcolors.css'

export function GroupColorsButton({ groups, onChange }: { groups: string[]; onChange?: () => void }) {
  const [open, setOpen] = useState(false)
  const [, bump] = useState(0)
  const [note, setNote] = useState('')
  const [toLeft, setToLeft] = useState(false)       // у правого края окна список раскрывается влево
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { void loadGroupColorOverrides() }, [])
  useEffect(() => onGroupColorsChange(() => { bump(n => n + 1); onChange?.() }), [onChange])
  const colors = groupColors(groups)
  const names = Object.keys(colors)
  const save = async (g: string, c: string | null) => {
    try { setNote(''); await saveGroupColor(g, c) } catch { setNote('Не удалось сохранить цвет: нет связи с программой.') }
  }
  if (names.length < 2) return null
  return (
    <div className="gcol" ref={box}>
      <button type="button" className="gcol-btn" aria-expanded={open} onClick={() => { setToLeft((box.current?.getBoundingClientRect().left ?? 0) + 316 > window.innerWidth); setOpen(!open) }} title="Цвет каждой группы одинаков во всех программах; можно выбрать свой">
        <span className="gcol-dots">{names.slice(0, 5).map(g => <i key={g} style={{ background: colors[g] }} />)}</span>Цвета групп
      </button>
      {open && (
        <div className={'gcol-pop' + (toLeft ? ' left' : '')} role="dialog" aria-label="Цвета групп">
          <p className="gcol-hint">Цвет группы один во всех программах и на всех графиках. Выбранный вручную запоминается и главнее палитры.</p>
          <ul>
            {names.map(g => (
              <li key={g}>
                <input type="color" value={colors[g]} aria-label={'Цвет ' + g} onChange={e => void save(g, e.target.value)} />
                <span className="gcol-name">{g}</span>
                {hasGroupColorOverride(g) ? <button type="button" className="gcol-reset" onClick={() => void save(g, null)}>Сбросить</button> : <span className="gcol-auto">палитра</span>}
              </li>
            ))}
          </ul>
          <div className="gcol-foot">
            <button type="button" onClick={() => void save('*', null)}>Сбросить все на палитру</button>
            <button type="button" onClick={() => setOpen(false)}>Закрыть</button>
          </div>
          {note && <p className="gcol-note">{note}</p>}
        </div>
      )}
    </div>
  )
}
