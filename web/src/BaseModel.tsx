import { useEffect, useState } from 'react'
import { importApi, type BaseModelCell, type BaseModelState } from './api_import'
import type { Project } from './api'

const STATE_TEXT: Record<BaseModelCell['state'], string> = { same: 'совпало', diff: 'расходится', only_model: 'есть только в модели', only_file: 'есть только в файле' }
const num = (v: number | null) => (v === null ? '—' : v.toLocaleString('ru-RU', { maximumFractionDigits: 1 }))

/** Базовая модель проекта: из неё берутся устье, альтитуда и перфорация скважин. Это подсказка: сверка с файлом видна,
 *  в таблицу значения попадают только по кнопке, файл можно оставить главным. */
export function BaseModel({ project, onProject }: { project: Project | null; onProject?: (p: Project) => void }) {
  const [state, setState] = useState<BaseModelState | null>(null)
  const [fields, setFields] = useState<string[]>(['x', 'y', 'perf'])
  const [mode, setMode] = useState<'fill' | 'replace'>('fill')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const pid = project?.id

  useEffect(() => {
    setState(null)
    if (pid) importApi.baseModel(pid).then(setState).catch(e => setMessage((e as Error).message))
  }, [pid])

  if (!project || !state) return message ? <div className="note warning">{message}</div> : null
  const run = async (job: () => Promise<void>) => {
    setBusy(true); setMessage('')
    try { await job() } catch (e) { setMessage((e as Error).message) } finally { setBusy(false) }
  }
  const choose = (model: string) => run(async () => setState(await importApi.chooseBaseModel(project.id, model)))
  const apply = () => run(async () => {
    const r = await importApi.applyBaseModel(project.id, fields, mode)
    setState(r.state); setMessage(r.message); onProject?.(r.project)
  })
  const toggle = (k: string) => setFields(fields.includes(k) ? fields.filter(x => x !== k) : [...fields, k])
  const cmp = state.compare
  const diffRows = cmp ? cmp.rows : []

  return (
    <section className="folder-sources" aria-label="Базовая модель">
      <h2>Базовая модель</h2>
      <p className="muted small">Из входных файлов модели (.data) берутся устье X, Y, альтитуда и интервалы перфорации. Значения только предлагаются:
        сверка с загруженным файлом ниже, в проект они попадают по кнопке. Файл остаётся главным, пока вы не выберете «заменить».
        Карты и ГДМ читают тот же проект.</p>
      {!state.available && <div className="note warning">{state.error}</div>}
      {state.available && (
        <div className="row">
          <label>Модель{' '}
            <select disabled={busy} value={state.selected} onChange={e => choose(e.target.value)}>
              <option value="">не выбрана</option>
              {state.selected && !state.models.some(m => m.id === state.selected) && <option value={state.selected}>{state.selected}</option>}
              {state.models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select></label>
          <span className="muted small">список — из общего списка папок tNavigator</span>
        </div>
      )}
      {state.error_model && <div className="note warning">{state.error_model}</div>}
      {state.notes.length > 0 && <details><summary className="small">Замечания к чтению модели: {state.notes.length}</summary>
        <ul>{state.notes.slice(0, 20).map((n, i) => <li key={i} className="small">{n}</li>)}</ul></details>}
      {cmp && (
        <>
          <table className="raw"><thead><tr><th>Параметр</th><th>совпало</th><th>расходится</th><th>только в модели</th><th>только в файле</th><th>взять</th></tr></thead>
            <tbody>{state.fields.map(f => <tr key={f.key}><td>{f.label}</td>
              <td>{cmp.counts[f.key].same}</td><td>{cmp.counts[f.key].diff}</td><td>{cmp.counts[f.key].only_model}</td><td>{cmp.counts[f.key].only_file}</td>
              <td><input type="checkbox" checked={fields.includes(f.key)} onChange={() => toggle(f.key)} aria-label={'Взять из модели: ' + f.label} /></td></tr>)}</tbody></table>
          <div className="row">
            <label><input type="radio" checked={mode === 'fill'} onChange={() => setMode('fill')} /> дополнить только пропуски (файл главнее)</label>
            <label><input type="radio" checked={mode === 'replace'} onChange={() => setMode('replace')} /> заменить значениями модели</label>
            <button disabled={busy || !fields.length} onClick={apply}>Взять из модели</button>
          </div>
          <p className="muted small">Альтитуды лучше сверять с файлом: по умолчанию они не отмечены.</p>
          {diffRows.length > 0 && (
            <details><summary className="small">Расхождения и недостающие значения: скважин {diffRows.length}{cmp.truncated ? ` (показаны первые, ещё ${cmp.truncated})` : ''}</summary>
              <table className="raw"><thead><tr><th>Скважина</th><th>Поле</th><th>Модель</th><th>Файл</th><th>Статус</th></tr></thead>
                <tbody>{diffRows.flatMap(r => Object.entries(r).filter(([k, v]) => k !== 'well' && typeof v === 'object' && (v as BaseModelCell).state !== 'same')
                  .map(([k, v]) => <tr key={r.well + k}><td>{r.well}</td><td>{k}</td><td>{num((v as BaseModelCell).model)}</td><td>{num((v as BaseModelCell).file)}</td>
                    <td>{STATE_TEXT[(v as BaseModelCell).state]}</td></tr>))}</tbody></table></details>
          )}
        </>
      )}
      {message && <div className="note">{message}</div>}
    </section>
  )
}
