import { useEffect, useState } from 'react'

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

/** Поле границы периода: можно ввести ГГГГ, ММ.ГГГГ или ДД.ММ.ГГГГ. Применённая дата показывается рядом (последнее слово за инженером). */
export function PeriodDate({ value, end, onChange, disabled, label }: {
  value: string | null; end: boolean; onChange: (iso: string | null) => void
  disabled?: boolean; label?: string
}) {
  const [text, setText] = useState(value ? show(value) : '')
  useEffect(() => { setText(value ? show(value) : '') }, [value])
  const parsed = parsePartialDate(text, end)
  const commit = () => {
    if (parsed === null) { setText(value ? show(value) : ''); return }
    const bounded = parsed
    onChange(bounded || null)
    setText(bounded ? show(bounded) : '')
  }
  const partial = parsed && text.trim() !== show(parsed)
  return (
    <span className="period-date">
      <input type="text" inputMode="numeric" placeholder="ГГГГ или ДД.ММ.ГГГГ" value={text} disabled={disabled} aria-label={label}
        aria-invalid={parsed === null} style={{ width: 130 }}
        title={end ? 'Можно ввести только год: 2020 — по 31.12.2020; 03.2020 — по 31.03.2020.' : 'Можно ввести только год: 2020 — с 01.01.2020; 03.2020 — с 01.03.2020.'}
        onChange={e => setText(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') commit() }} />
      {partial && <span className="muted small"> → {show(parsed!)}</span>}
      {parsed === null && <span className="muted small"> неверная дата</span>}
    </span>
  )
}

/** Параметр — правая граница периода (то же правило, что `is_end_param` в atlas/contract.py). */
export const isEndParam = (name: string) => ['end', 'stop', 'date_to'].includes(name) || name.endsWith('_to') || name.endsWith('_end')
