// Редактор одного листа: строка заголовков, имена колонок, тип, сопоставление полей (import_editor.sheet_editor 5.8).
import { useEffect, useMemo, useState } from 'react'
import { importApi, type Choice, type SheetRequest, type SheetState, type Spec } from './api_import'

interface Props {
  request: SheetRequest
  sheetTypes: Choice[]
  fields: Choice[]
  pressureFields: Record<string, string>
  rememberable?: boolean
  onChange: (spec: Spec | null, valid: boolean) => void
}

const NONE = -1

export function SheetEditor({ request, sheetTypes, fields: allFields, pressureFields, rememberable, onChange }: Props) {
  const { token, sheet, encoding, delimiter, mode, pressure, fonds } = request
  const [header, setHeader] = useState<number | null>(null)
  const [module, setModule] = useState<string | null>(null)
  const [state, setState] = useState<SheetState | null>(null)
  const [failure, setFailure] = useState('')
  const [enabled, setEnabled] = useState(sheet !== 'Инструкция')
  const [names, setNames] = useState<string[]>([])
  const [fields, setFields] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<string, number>>({})
  const [wide, setWide] = useState(false)
  const [wellcols, setWellcols] = useState<number[]>([])
  const [pairs, setPairs] = useState<number[][]>([])
  const [remembered, setRemembered] = useState(false)

  useEffect(() => { setHeader(null); setModule(null) }, [token, sheet, encoding, delimiter, fonds])
  useEffect(() => {
    const ctrl = new AbortController()
    setFailure('')
    importApi.sheet({ token, sheet, encoding, delimiter, mode, pressure, fonds, header, module }, ctrl.signal)
      .then(s => {
        setState(s)
        if (s.empty) return
        setNames(s.labels); setFields(s.fields); setMapping(s.mapping); setWide(s.wide)
        setWellcols(s.wellcols); setPairs(s.fond_pairs); setRemembered(s.remembered)
      })
      .catch(e => { if ((e as Error).name !== 'AbortError') setFailure((e as Error).message) })
    return () => ctrl.abort()
  }, [token, sheet, encoding, delimiter, mode, pressure, fonds, header, module])

  const columns = useMemo(() => names.map((_, i) => i), [names])
  const shownFields = pressure ? (wide ? ['date'] : fonds ? ['well', 'fond'] : ['date', 'well', 'value']) : wide ? ['date'] : fields
  const label = (f: string) => pressure ? (pressureFields[f] ?? f) : (allFields.find(x => x.value === f)?.label ?? f)
  const display = (i: number) => i === NONE ? '— не выбрано —' : `${i + 1} · ${names[i] || '(пустая шапка)'}`

  const spec: Spec | null = useMemo(() => {
    if (!state || state.empty) return null
    const used: Record<string, number> = {}
    for (const f of shownFields) if ((mapping[f] ?? NONE) >= 0 && !(fonds && pressure)) used[f] = mapping[f]
    return {
      enabled, header: state.header, mapping: used, wide, wellcols: wide ? wellcols : [],
      names: Object.fromEntries(names.map((n, i) => [String(i), n])),
      fond_pairs: fonds ? pairs : [], ...(pressure ? {} : { module: state.module }),
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, enabled, mapping, wide, wellcols, names, pairs, fields])
  const problems: string[] = []
  if (spec && spec.enabled) {
    const cols = Object.values(spec.mapping)
    if (new Set(cols).size !== cols.length) problems.push('Одной колонке назначены разные поля. Исправьте сопоставление.')
    if (wide && !wellcols.length) problems.push('Выберите хотя бы одну колонку скважины.')
    if (fonds && pairs.some(([a, b]) => a === b)) problems.push('Скважина и фонд должны быть в разных колонках.')
  }
  const valid = problems.length === 0
  useEffect(() => { onChange(state?.empty ? { enabled: false } as Spec : spec, valid) // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, valid])

  const remember = async (on: boolean) => {
    if (!spec) return
    try {
      const r = await importApi.profile({ ...request, spec, remember: on })
      setRemembered(r.remembered)
    } catch (e) { setFailure((e as Error).message) }
  }

  if (failure) return <div className="sheet-editor"><strong>Лист: {sheet}</strong><div className="note warning">{failure}</div></div>
  if (!state) return <div className="sheet-editor"><strong>Лист: {sheet}</strong><p className="muted">Загрузка…</p></div>
  if (state.empty) return <div className="sheet-editor"><strong>Лист: {sheet}</strong><div className="note info">Пустой лист</div></div>

  return (
    <div className="sheet-editor">
      <strong>Лист: {sheet}</strong>
      <p className="muted small">Исходный файл: первые 31 строка; номера строк слева соответствуют файлу. Значения не изменяются.</p>
      <div className="sheet-preview">
        <table>
          <thead><tr><th />{state.preview.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {state.preview.rows.map((r, i) => (
              <tr key={i} className={i === state.header ? 'header-row' : undefined}>
                <th>{i + 1}</th>{r.map((v, j) => <td key={j}>{v}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label className="toggle"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /><span>Использовать лист</span></label>
      {enabled && (
        <>
          <div className="form-row">
            <label className="field">Строка заголовков
              <input type="number" min={0} max={state.max_header + 1} value={state.header + 1}
                     title="Нумерация с 1. Значение 0 — заголовков нет, первая строка содержит данные."
                     onChange={e => setHeader(Math.max(-1, Math.min(state.max_header, Number(e.target.value) - 1)))} />
            </label>
            {!pressure && (
              <label className="field">Тип данных
                <select value={state.module} onChange={e => setModule(e.target.value)}>
                  {sheetTypes.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </label>
            )}
            {pressure && !fonds && (
              <label className="field">Структура
                <select value={wide ? '1' : '0'} onChange={e => setWide(e.target.value === '1')}>
                  <option value="0">Строки: дата, скважина, давление</option>
                  <option value="1">Матрица: даты и колонки скважин</option>
                </select>
              </label>
            )}
            {!pressure && (
              <label className={'toggle' + (state.wide_allowed ? '' : ' disabled')}>
                <input type="checkbox" checked={wide} disabled={!state.wide_allowed} onChange={e => setWide(e.target.checked)} />
                <span>Матрица расходов: скважины по колонкам</span>
              </label>
            )}
          </div>
          <details>
            <summary>Имена колонок ({names.length})</summary>
            <table className="names">
              <thead><tr><th>Колонка</th><th>Исходная шапка</th><th>Используемое имя</th></tr></thead>
              <tbody>
                {names.map((n, i) => (
                  <tr key={i}><td>{i + 1}</td><td>{state.labels[i]}</td>
                    <td><input value={n} onChange={e => setNames(names.map((v, j) => (j === i ? e.target.value : v)))} /></td></tr>
                ))}
              </tbody>
            </table>
          </details>
          {!pressure && !wide && (
            <details>
              <summary>Поля для сопоставления: {fields.map(label).join(', ') || 'не выбраны'}</summary>
              <div className="checks">
                {allFields.map(f => (
                  <label key={f.value} className="check">
                    <input type="checkbox" checked={fields.includes(f.value)}
                           onChange={e => setFields(e.target.checked ? [...fields, f.value] : fields.filter(x => x !== f.value))} />
                    {f.label}
                  </label>
                ))}
              </div>
            </details>
          )}
          {!fonds && (
            <div className="form-grid">
              {shownFields.map(f => (
                <label key={f} className="field">{label(f)} ← колонка
                  <select value={mapping[f] ?? NONE} onChange={e => setMapping({ ...mapping, [f]: Number(e.target.value) })}>
                    {[NONE, ...columns].map(i => <option key={i} value={i}>{display(i)}</option>)}
                  </select>
                </label>
              ))}
            </div>
          )}
          {wide && (
            <details open>
              <summary>Колонки скважин: {wellcols.length} из {columns.length - 1}</summary>
              <div className="checks">
                {columns.filter(i => i !== (mapping.date ?? 0)).map(i => (
                  <label key={i} className="check">
                    <input type="checkbox" checked={wellcols.includes(i)}
                           onChange={e => setWellcols(e.target.checked ? [...wellcols, i].sort((a, b) => a - b) : wellcols.filter(x => x !== i))} />
                    {display(i)}
                  </label>
                ))}
              </div>
            </details>
          )}
          {fonds && (
            <div className="form-grid">
              <label className="field">Число пар «скважина / фонд»
                <input type="number" min={1} max={columns.length} value={pairs.length}
                       onChange={e => {
                         const n = Math.max(1, Math.min(columns.length, Number(e.target.value) || 1))
                         setPairs(Array.from({ length: n }, (_, k) => pairs[k] ?? [0, Math.min(1, columns.length - 1)]))
                       }} />
              </label>
              {pairs.map(([w, f], k) => (
                <div key={k} className="pair">
                  <label className="field">Скважина · пара {k + 1}
                    <select value={w} onChange={e => setPairs(pairs.map((p, j) => (j === k ? [Number(e.target.value), p[1]] : p)))}>
                      {columns.map(i => <option key={i} value={i}>{display(i)}</option>)}
                    </select>
                  </label>
                  <label className="field">Фонд · пара {k + 1}
                    <select value={f} onChange={e => setPairs(pairs.map((p, j) => (j === k ? [p[0], Number(e.target.value)] : p)))}>
                      {columns.map(i => <option key={i} value={i}>{display(i)}</option>)}
                    </select>
                  </label>
                </div>
              ))}
            </div>
          )}
          {problems.map(p => <div key={p} className="note warning">{p}</div>)}
          {rememberable && (
            <label className="toggle" title="В следующий раз такая разметка применится автоматически.">
              <input type="checkbox" checked={remembered} disabled={!valid} onChange={e => remember(e.target.checked)} />
              <span>Запомнить для файлов с такой же шапкой</span>
            </label>
          )}
        </>
      )}
    </div>
  )
}
