import { useEffect, useRef, useState } from 'react'
import { api } from './api'

/** Единый разбор неполной даты для границ периода (то же правило, что `parse_partial_date` в atlas/contract.py):
 *  «2020» → 01.01.2020 (начало) / 31.12.2020 (конец); «03.2020» → 01.03 / 31.03; полная дата — как есть. '' — без границы. */
export function parsePartialDate(text: string, end: boolean): string | null {
  const t = text.trim()
  if (!t) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  const ok = (y: number, m: number, d: number) => {
    const dt = new Date(Date.UTC(y, m - 1, d))
    return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d ? `${y}-${pad(m)}-${pad(d)}` : null
  }
  const lastDay = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate()
  let m = /^(\d{4})$/.exec(t)
  if (m) return end ? `${m[1]}-12-31` : `${m[1]}-01-01`
  m = /^(\d{4})[-./](\d{1,2})$/.exec(t)
  if (m) { const y = +m[1], mo = +m[2]; return mo >= 1 && mo <= 12 ? ok(y, mo, end ? lastDay(y, mo) : 1) : null }
  m = /^(\d{1,2})[-./](\d{4})$/.exec(t)
  if (m) { const y = +m[2], mo = +m[1]; return mo >= 1 && mo <= 12 ? ok(y, mo, end ? lastDay(y, mo) : 1) : null }
  m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(t)
  if (m) return ok(+m[1], +m[2], +m[3])
  m = /^(\d{1,2})[./](\d{1,2})[./](\d{4})$/.exec(t)
  if (m) return ok(+m[3], +m[2], +m[1])
  return null
}

const show = (iso: string) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : '')

const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
type SeasonItem = { kind: string; label: string; start: string; end: string }
const seasonCache = new Map<string, SeasonItem[]>()

/** Дата из первого числа месяца: «барабан» месяца и года. */
export const firstOfMonth = (year: number, month: number) => `${year}-${String(month).padStart(2, '0')}-01`

/** Поле границы периода — ЕДИНЫЙ компонент для всех модулей. Три способа задать дату: список сезонов отбора и закачки
 *  (для левой границы — начало сезона, для правой — конец), барабан «месяц + год» (всегда 1-е число) и вставка из буфера обмена.
 *  Ручной ввод (ГГГГ, ММ.ГГГГ, ДД.ММ.ГГГГ) остаётся. Применённая дата показывается рядом (последнее слово за инженером). */
export function PeriodDate({ value, end, onChange, disabled, label, project }: {
  value: string | null; end: boolean; onChange: (iso: string | null) => void
  disabled?: boolean; label?: string; project?: string
}) {
  const [text, setText] = useState(value ? show(value) : '')
  const [open, setOpen] = useState(false)
  const [seasons, setSeasons] = useState<SeasonItem[]>([])
  const [note, setNote] = useState('')
  const box = useRef<HTMLSpanElement>(null)
  useEffect(() => { setText(value ? show(value) : '') }, [value])
  useEffect(() => {
    if (!open || !project) return
    const cached = seasonCache.get(project)
    if (cached) { setSeasons(cached); return }
    let alive = true
    api.projectSeasons(project).then(l => { seasonCache.set(project, l); if (alive) setSeasons(l) }).catch(() => { if (alive) setSeasons([]) })
    return () => { alive = false }
  }, [open, project])
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const parsed = parsePartialDate(text, end)
  const apply = (iso: string | null) => { onChange(iso); setText(iso ? show(iso) : ''); setNote(''); setOpen(false) }
  const commit = () => {
    if (parsed === null) { setText(value ? show(value) : ''); return }
    onChange(parsed || null)
    setText(parsed ? show(parsed) : '')
  }
  const paste = async () => {
    let clip = ''
    try { clip = await navigator.clipboard.readText() } catch { /* нет доступа к буферу */ }
    if (!clip) { setNote('Буфер недоступен: вставьте дату в поле (Ctrl+V)'); return }
    const iso = parsePartialDate(clip.split(/\r?\n/)[0], end)
    if (!iso) { setNote(`«${clip.trim().slice(0, 24)}» — не дата`); return }
    apply(iso)
  }
  const base = value ? new Date(value + 'T00:00:00') : new Date()
  const year = base.getFullYear(), month = base.getMonth() + 1
  const years = Array.from({ length: 41 }, (_, k) => new Date().getFullYear() - 30 + k)
  if (!years.includes(year)) years.push(year)
  const partial = parsed && text.trim() !== show(parsed)
  return (
    <span className="period-date" ref={box} style={{ position: 'relative' }}>
      <input type="text" inputMode="numeric" placeholder="ГГГГ или ДД.ММ.ГГГГ" value={text} disabled={disabled} aria-label={label}
        aria-invalid={parsed === null} style={{ width: 130 }}
        title={end ? 'Можно ввести только год: 2020 — по 31.12.2020; 03.2020 — по 31.03.2020.' : 'Можно ввести только год: 2020 — с 01.01.2020; 03.2020 — с 01.03.2020.'}
        onChange={e => setText(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') commit() }} />
      <button type="button" className="period-open" disabled={disabled} aria-label="Выбрать период" title="Сезон, месяц и год, вставка даты"
        onClick={() => setOpen(o => !o)}>▾</button>
      {partial && <span className="muted small"> → {show(parsed!)}</span>}
      {parsed === null && <span className="muted small"> неверная дата</span>}
      {open && (
        <div className="period-pop" role="dialog" style={{ position: 'absolute', zIndex: 30, top: '100%', left: 0, minWidth: 240, padding: 8, display: 'grid', gap: 8,
          background: 'var(--panel, #fff)', border: '1px solid var(--line, #ccc)', borderRadius: 6, boxShadow: '0 4px 14px rgba(0,0,0,.18)' }}>
          {project && (
            <label className="field">
              <span className="field-label">Сезон ({end ? 'конец' : 'начало'})</span>
              <select value="" onChange={e => { const s = seasons[Number(e.target.value)]; if (s) apply(end ? s.end : s.start) }}>
                <option value="" disabled>{seasons.length ? 'Выберите сезон…' : 'Нет сезонов'}</option>
                {seasons.map((s, i) => <option key={i} value={i}>{s.label}</option>)}
              </select>
            </label>
          )}
          <div className="field">
            <span className="field-label">Месяц и год (1-е число)</span>
            <span style={{ display: 'flex', gap: 4 }}>
              <select aria-label="Месяц" value={month} onChange={e => apply(firstOfMonth(year, Number(e.target.value)))}>
                {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
              </select>
              <select aria-label="Год" value={year} onChange={e => apply(firstOfMonth(Number(e.target.value), month))}>
                {years.sort((a, b) => a - b).map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </span>
          </div>
          <button type="button" onClick={paste}>Вставить дату из буфера</button>
          {value && <button type="button" onClick={() => apply(null)}>Снять границу</button>}
          {note && <span className="muted small">{note}</span>}
        </div>
      )}
    </span>
  )
}

/** Параметр — правая граница периода (то же правило, что `is_end_param` в atlas/contract.py). */
export const isEndParam = (name: string) => ['end', 'stop', 'date_to'].includes(name) || name.endsWith('_to') || name.endsWith('_end')
