import { useEffect, useMemo, useState } from 'react'
import type { Assignments, Cell, Table } from './api'
import { formatCell } from './format'

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
}

export function TableView({ table, onDownload, onApply, onAssign }: Props) {
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
          <table>
            <thead>
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
                  <tr key={i} className={(on ? 'is-excluded' : '') + (changed ? ' is-changed' : '')}>
                    {action && id !== undefined && (
                      <td className="check"><input type="checkbox" checked={on} onChange={() => flip(id)} aria-label={action.column ?? 'Исключить'} /></td>
                    )}
                    {table.columns.map((c, k) => assign?.editable.includes(c.key) ? (
                      <td key={c.key} className="edit">
                        <input value={current(i, c.key)} maxLength={200} aria-label={c.label}
                          onChange={e => edit(i, c.key, e.target.value)} />
                      </td>
                    ) : <td key={c.key} className={c.kind}>{formatCell(table.rows[k][i], c)}</td>)}
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
            {assign.submit === 'all' ? `Скважин: ${assignCount}` : assignCount ? `Изменено скважин: ${assignCount}` : 'Измените ячейки'}
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
        <button type="button" className="quiet small" onClick={e => { e.preventDefault(); copy() }} title="Скопировать для вставки в Excel">Копировать</button>
        {(['xlsx', 'csv'] as const).map(f => (
          <button key={f} type="button" className="quiet small" title={f === 'csv' ? 'CSV с разделителем «;» для Excel' : undefined}
            onClick={e => { e.preventDefault(); onDownload(f).catch(err => setFailure((err as Error).message)) }}>{f.toUpperCase()}</button>
        ))}
      </span>
    </>
  )

  return table.collapsed ? (
    <details className="table-block">
      <summary className="block-head">{head}</summary>
      {body}
    </details>
  ) : (
    <section className="table-block">
      <header className="block-head">{head}</header>
      {body}
    </section>
  )
}
