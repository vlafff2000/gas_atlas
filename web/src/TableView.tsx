import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { Assignments, Cell, Column, Table } from './api'
import { formatCell } from './format'
import { tableBars, usePref } from './chartPrefs'

const PAGE = 500

function compare(a: Cell, b: Cell) {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), 'ru', { numeric: true })
}
const blank = (v: Cell) => v === null || v === ''

interface Props {
  table: Table
  onDownload: (format: 'xlsx' | 'csv') => Promise<void>
  onApply?: (add: string[], remove: string[], reason: string) => Promise<void>
  onAssign?: (changes: Assignments, journal: string) => Promise<void>
  onLoad?: () => Promise<Table>      // для таблицы с `deferred`: полные строки
  onRow?: (index: number) => void    // щелчок по строке (индекс в исходной таблице); для журнала проверки импорта
  rowOpen?: (index: number) => boolean   // строку можно открыть (иначе щелчок не работает)
}

export function TableView({ table: given, onDownload, onApply, onAssign, onLoad, onRow, rowOpen }: Props) {
  const [loaded, setLoaded] = useState<Table | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => { setLoaded(null) }, [given])
  const table = loaded ?? given
  const load = (open: boolean) => {
    if (!open || !table.deferred || loading || !onLoad) return
    setLoading(true)
    onLoad().then(setLoaded).catch(e => setFailure((e as Error).message)).finally(() => setLoading(false))
  }
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null)
  const [limit, setLimit] = useState(PAGE)
  const action = table.action?.kind === 'exclude' ? table.action : null
  const assign = table.action?.kind === 'assign' ? table.action : null
  const [edits, setEdits] = useState<Assignments>({})
  useEffect(() => { setEdits({}) }, [assign])
  const initial = useMemo(() => new Set(action?.ids.filter((_, i) => action.checked?.[i]) ?? []), [action])
  const [checked, setChecked] = useState<Set<string>>(initial)
  const [reason, setReason] = useState(action?.reason ?? '')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  useEffect(() => { setChecked(new Set(initial)) }, [initial])
  useEffect(() => { setReason(action?.reason ?? '') }, [action?.reason])

  // мини-полоски в числовых ячейках: доля от наибольшего по модулю значения столбца
  const bars = usePref(tableBars)
  const scale = useMemo(() => table.columns.map((c, k) => {
    if (c.kind !== 'number' || c.key.startsWith('_')) return 0
    let max = 0, distinct = new Set<number>()
    for (const v of table.rows[k]) if (typeof v === 'number' && Number.isFinite(v)) { max = Math.max(max, Math.abs(v)); if (distinct.size < 3) distinct.add(v) }
    return distinct.size > 2 ? max : 0
  }), [table])
  const tone = (v: unknown, c: Column) => typeof v === 'number' && Number.isFinite(v) && c.good != null ? (v >= c.good ? ' tone-good' : ' tone-poor') : ''
  const hasBars = scale.some(m => m > 0)
  const barStyle = (v: unknown, k: number) => {
    if (!bars || !scale[k] || typeof v !== 'number' || !Number.isFinite(v)) return undefined
    const share = Math.min(100, Math.abs(v) / scale[k] * 100)
    return { '--bar-w': share.toFixed(1) + '%', '--bar-c': v < 0 ? 'var(--bar-negative)' : 'var(--bar)' } as CSSProperties
  }

  const order = useMemo(() => {
    const idx = Array.from({ length: table.count }, (_, i) => i)
    if (sort) {
      const values = table.rows[sort.col]
      idx.sort((i, j) => {
        const a = values[i], b = values[j]
        if (blank(a) || blank(b)) return blank(a) === blank(b) ? 0 : blank(a) ? 1 : -1   // пустые всегда внизу
        return compare(a, b) * sort.dir
      })
    }
    return idx
  }, [table, sort])

  const toggleSort = (col: number) =>
    setSort(s => (s?.col === col ? (s.dir === 1 ? { col, dir: -1 } : null) : { col, dir: 1 }))

  const copy = () => {
    const head = table.columns.map(c => (c.unit ? `${c.label}, ${c.unit}` : c.label)).join('\t')
    const body = order.map(i => table.columns.map((c, k) => formatCell(table.rows[k][i], c)).join('\t')).join('\n')
    navigator.clipboard?.writeText(head + '\n' + body)
  }

  const add = action ? [...checked].filter(id => !initial.has(id)) : []
  const remove = action ? [...initial].filter(id => !checked.has(id)) : []
  const changes = add.length + remove.length
  const flip = (id: string) => setChecked(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const apply = async () => {
    if (!onApply || !changes) return
    setBusy(true); setFailure('')
    try { await onApply(add, remove, reason) } catch (e) { setFailure((e as Error).message) } finally { setBusy(false) }
  }

  // Назначение групп: правка ячеек и отправка изменённых (или всех) строк.
  const original = (i: number, field: string) => String(assign?.values[field]?.[i] ?? '')
  const current = (i: number, field: string) => edits[assign!.ids[i]]?.[field] ?? original(i, field)
  const edit = (i: number, field: string, value: string) =>
    setEdits(e => ({ ...e, [assign!.ids[i]]: { ...e[assign!.ids[i]], [field]: value } }))
  const rowChanged = (i: number) => !!assign && assign.fields.some(f => current(i, f) !== original(i, f))
  const assignments: Assignments = {}
  if (assign) {
    assign.ids.forEach((id, i) => {
      if (assign.submit === 'all' || rowChanged(i)) assignments[id] = Object.fromEntries(assign.fields.map(f => [f, current(i, f)]))
    })
  }
  const assignCount = Object.keys(assignments).length
  const rows = assign?.target === 'object-categories' ? 'Объектов' : 'Скважин'
  const submitAssign = async () => {
    if (!onAssign || !assign || !assignCount) return
    setBusy(true); setFailure('')
    try { await onAssign(assignments, assign.journal); setEdits({}) }
    catch (e) { setFailure((e as Error).message) } finally { setBusy(false) }
  }

  const body = (
    <>
      {table.count === 0 ? <p className="muted table-empty">Нет строк для выбранных условий.</p> : (
        <div className="table-scroll">
          <table className={(action ? 'has-check' : '') + (table.columns.length > 2 ? ' frozen' : '')}>
            <thead>
              {table.header?.map((row, r) => (
                <tr key={`h${r}`} className="header-group">
                  {action && <th className="check" />}
                  {row.map(([label, span], k) => <th key={k} colSpan={span} className={label ? 'group-label' : ''}>{label}</th>)}
                </tr>
              ))}
              <tr>
                {action && <th className="check">{action.column ?? 'Исключить'}</th>}
                {table.columns.map((c, k) => (
                  <th key={c.key} className={c.kind} aria-sort={sort?.col === k ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                    <button type="button" onClick={() => toggleSort(k)}>
                      {c.label}{c.unit && <span className="unit">{c.unit}</span>}
                      <span className="sort-mark">{sort?.col === k ? (sort.dir === 1 ? '▲' : '▼') : ''}</span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {order.slice(0, limit).map(i => {
                const id = action?.ids[i]
                const on = id !== undefined && checked.has(id)
                const changed = (id !== undefined && on !== initial.has(id)) || rowChanged(i)
                return (
                  <tr key={i} className={(on ? 'is-excluded' : '') + (changed ? ' is-changed' : '') + (onRow && (!rowOpen || rowOpen(i)) ? ' clickable' : '')}
                      onClick={onRow && (!rowOpen || rowOpen(i)) ? () => onRow(i) : undefined}
                      title={onRow && (!rowOpen || rowOpen(i)) ? 'Открыть эту строку в таблице файла' : undefined}>
                    {action && id !== undefined && (
                      <td className="check"><input type="checkbox" checked={on} onChange={() => flip(id)} aria-label={action.column ?? 'Исключить'} /></td>
                    )}
                    {table.columns.map((c, k) => assign?.editable.includes(c.key) ? (
                      <td key={c.key} className="edit">
                        <input value={current(i, c.key)} maxLength={200} aria-label={c.label}
                          onChange={e => edit(i, c.key, e.target.value)} />
                      </td>
                    ) : (
                      <td key={c.key} className={c.kind + (barStyle(table.rows[k][i], k) ? ' bar' : '') + tone(table.rows[k][i], c)} style={barStyle(table.rows[k][i], k)}>
                        {formatCell(table.rows[k][i], c)}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {table.count > limit && (
        <button type="button" className="quiet more" onClick={() => setLimit(l => l + PAGE)}>
          Показать ещё {Math.min(PAGE, table.count - limit)} из {table.count - limit}
        </button>
      )}
      {action && table.count > 0 && (
        <div className="table-action">
          {action.reason_editable && (
            <label className="inline-field">Причина исключения
              <input value={reason} onChange={e => setReason(e.target.value)} maxLength={300} />
            </label>
          )}
          <button type="button" className="primary" disabled={!changes || busy} onClick={apply}>
            {busy ? 'Сохраняю…' : action.label}
          </button>
          <span className="muted">
            {changes ? `Исключить: ${add.length}, вернуть: ${remove.length}` : 'Отметьте строки'}
          </span>
          {failure && <span className="field-error">{failure}</span>}
        </div>
      )}
      {assign && table.count > 0 && onAssign && (
        <div className="table-action">
          <button type="button" className="primary" disabled={!assignCount || busy} onClick={submitAssign}>
            {busy ? 'Сохраняю…' : assign.label}
          </button>
          <span className="muted">
            {assign.submit === 'all' ? `${rows}: ${assignCount}` : assignCount ? `Изменено ${rows.toLowerCase()}: ${assignCount}` : 'Измените ячейки'}
          </span>
          {failure && <span className="field-error">{failure}</span>}
        </div>
      )}
      {table.note && <p className="table-note">{table.note}</p>}
    </>
  )

  const head = (
    <>
      <h3>{table.title}</h3>
      <span className="muted">{table.count} строк</span>
      <span className="head-actions">
        {hasBars && (
          <button type="button" className={'quiet small' + (bars ? ' on' : '')} aria-pressed={bars}
            onClick={e => { e.preventDefault(); tableBars.set(!bars) }} title="Полоски в числовых ячейках: величина относительно столбца">Полоски</button>
        )}
        <button type="button" className="quiet small" onClick={e => { e.preventDefault(); copy() }} title="Скопировать для вставки в Excel">Копировать</button>
        {(['xlsx', 'csv'] as const).map(f => (
          <button key={f} type="button" className="quiet small" title={f === 'csv' ? 'CSV с разделителем «;» для Excel' : undefined}
            onClick={e => { e.preventDefault(); onDownload(f).catch(err => setFailure((err as Error).message)) }}>{f.toUpperCase()}</button>
        ))}
      </span>
    </>
  )

  return table.collapsed ? (
    <details className="table-block" onToggle={e => load((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="block-head">{head}</summary>
      {table.deferred ? <p className="muted table-empty">{failure || 'Загружаю строки…'}</p> : body}
    </details>
  ) : (
    <section className="table-block">
      <header className="block-head">{head}</header>
      {body}
    </section>
  )
}
