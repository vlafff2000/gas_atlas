import { useEffect, useState } from 'react'
import { importApi, type BaseModelCell, type BaseModelInventory, type BaseModelState } from './api_import'
import { openFilePicker } from './FilePicker'
import type { Project } from './api'

const STATE_TEXT: Record<BaseModelCell['state'], string> = { same: 'совпало', diff: 'расходится', only_model: 'есть только в модели', only_file: 'есть только в файле' }
const num = (v: number | null) => (v === null ? '—' : v.toLocaleString('ru-RU', { maximumFractionDigits: 1 }))

/** Базовая модель проекта: из неё берутся устье, альтитуда и перфорация скважин. Это подсказка: сверка с файлом видна,
 *  в таблицу значения попадают только по кнопке, файл можно оставить главным. Блок виден всегда, пока открыт проект. */
export function BaseModel({ project, onProject }: { project: Project | null; onProject?: (p: Project) => void }) {
  const [state, setState] = useState<BaseModelState | null>(null)
  const [fields, setFields] = useState<string[]>(['x', 'y', 'perf'])
  const [mode, setMode] = useState<'fill' | 'replace'>('fill')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [checklist, setChecklist] = useState<BaseModelInventory | 'loading' | null>(null)
  const pid = project?.id

  useEffect(() => {
    setState(null)
    if (pid) importApi.baseModel(pid).then(setState).catch(e => setMessage('Базовая модель: ' + (e as Error).message))
  }, [pid])

  if (!project) return null
  const run = async (job: () => Promise<void>) => {
    setBusy(true); setMessage('')
    try { await job() } catch (e) { setMessage((e as Error).message) } finally { setBusy(false) }
  }
  const choose = (body: { model?: string; data_dir?: string }) => run(async () => setState(await importApi.chooseBaseModel(project.id, body)))
  const addFolder = () => run(async () => {
    const folder = await openFilePicker({ mode: 'folder', title: 'Папка с результатами модели (там, где лежат EGRID, INIT, UNRST)' })
    if (!folder) return
    const r = await importApi.addModelFolder(folder)
    setState(await importApi.baseModel(project.id))
    setMessage(r.models ? `Папка добавлена, моделей найдено: ${r.models}` : 'Папка добавлена, но файлов модели (EGRID, INIT, SMSPEC, UNRST) в ней не нашлось')
  })
  const pickModelFile = () => run(async () => {
    const file = await openFilePicker({ mode: 'file', title: 'Любой файл результатов модели (EGRID, INIT, SMSPEC, UNRST)' })
    if (file) setState(await importApi.chooseBaseModel(project.id, { model: file }))
  })
  const pickDataDir = () => run(async () => {
    const folder = await openFilePicker({ mode: 'folder', start: state?.data_dir || undefined, title: 'Папка с входными файлами модели (.data и include)' })
    if (folder) setState(await importApi.chooseBaseModel(project.id, { data_dir: folder }))
  })
  const apply = () => run(async () => {
    const r = await importApi.applyBaseModel(project.id, fields, mode)
    setState(r.state); setMessage(r.message); onProject?.(r.project)
  })
  const openChecklist = () => { setChecklist('loading'); importApi.baseModelInventory(project.id).then(setChecklist).catch(e => { setChecklist(null); setMessage((e as Error).message) }) }
  const toggle = (k: string) => setFields(fields.includes(k) ? fields.filter(x => x !== k) : [...fields, k])
  const cmp = state?.compare
  const files = state?.data_files
  const known = state ? state.models.some(m => m.id === state.selected) : true

  return (
    <section className="folder-sources" aria-label="Базовая модель">
      <h2>Базовая модель</h2>
      <p className="muted small">Из входных файлов модели (.data) берутся устье X, Y, альтитуда и интервалы перфорации. Значения только предлагаются:
        сверка с загруженным файлом ниже, в проект они попадают по кнопке. Файл остаётся главным, пока вы не выберете «заменить».
        Карты и ГДМ читают тот же проект. <button type="button" onClick={openChecklist} disabled={!state?.selected && !state?.data_dir}>Что читается из модели…</button></p>
      {checklist && <BaseModelChecklist data={checklist === 'loading' ? null : checklist} onClose={() => setChecklist(null)} />}
      {!state && !message && <p className="muted small">Загрузка…</p>}
      {state && !state.available && <div className="note warning">{state.error}</div>}
      {state && state.available && (
        <>
          <div className="row">
            <label>Модель{' '}
              <select disabled={busy} value={state.selected} onChange={e => choose({ model: e.target.value })}>
                <option value="">не выбрана</option>
                {state.selected && !known && <option value={state.selected}>{state.selected}</option>}
                {state.models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select></label>
            <button disabled={busy} onClick={addFolder} title="Папка добавится в общий список tNavigator: его же видят Карты и ГДМ">Добавить папку с моделями…</button>
            <button disabled={busy} onClick={pickModelFile}>Выбрать файл модели…</button>
          </div>
          {!state.models.length && <p className="note">В общем списке папок tNavigator моделей нет. Нажмите «Добавить папку с моделями…» и укажите папку, где лежат
            результаты (EGRID, INIT, UNRST), или выберите файл модели. Нужна только папка с результатами: сводка SMSPEC/UNSMRY для базовой модели не обязательна.</p>}
          <div className="row">
            <span className="small">Путь до папки с .data:</span>
            <span title={state.data_dir}>{state.data_dir || <span className="muted">не задан, ищется рядом с результатами и на 1–3 папки выше</span>}</span>
            <button disabled={busy} onClick={pickDataDir}>Выбрать папку…</button>
            {state.data_dir && <button disabled={busy} onClick={() => choose({ data_dir: '' })}>Сбросить</button>}
          </div>
          {state.selected && files && (
            <p className="small muted">
              {files.used.length ? `Читаются файлы .data (${files.source === 'folder' ? 'из указанной папки' : 'найдены автоматически'}): ${files.used.join(', ')}`
                : 'Файлов .data не найдено: укажите папку с .data выше.'}
              {files.source === 'folder' && files.auto.length > 0 && files.auto.join() !== files.used.join() && ` Автопоиск нашёл бы другие: ${files.auto.join(', ')}.`}
            </p>)}
        </>
      )}
      {state?.error_model && <div className="note warning">{state.error_model}</div>}
      {state && state.notes.length > 0 && <details><summary className="small">Замечания к чтению модели: {state.notes.length}</summary>
        <ul>{state.notes.slice(0, 20).map((n, i) => <li key={i} className="small">{n}</li>)}</ul></details>}
      {state && cmp && (
        <>
          <table className="data-grid"><thead><tr><th>Параметр</th><th>совпало</th><th>расходится</th><th>только в модели</th><th>только в файле</th><th>взять</th></tr></thead>
            <tbody>{state.fields.map(f => <tr key={f.key}><td>{f.label}</td>
              <td>{cmp.counts[f.key].same}</td><td>{cmp.counts[f.key].diff}</td><td>{cmp.counts[f.key].only_model}</td><td>{cmp.counts[f.key].only_file}</td>
              <td><input type="checkbox" checked={fields.includes(f.key)} onChange={() => toggle(f.key)} aria-label={'Взять из модели: ' + f.label} /></td></tr>)}</tbody></table>
          <div className="row">
            <label><input type="radio" checked={mode === 'fill'} onChange={() => setMode('fill')} /> дополнить только пропуски (файл главнее)</label>
            <label><input type="radio" checked={mode === 'replace'} onChange={() => setMode('replace')} /> заменить значениями модели</label>
            <button disabled={busy || !fields.length} onClick={apply}>Взять из модели</button>
          </div>
          <p className="muted small">Альтитуды лучше сверять с файлом: по умолчанию они не отмечены.</p>
          {cmp.rows.length > 0 && (
            <details><summary className="small">Расхождения и недостающие значения: скважин {cmp.rows.length}{cmp.truncated ? ` (показаны первые, ещё ${cmp.truncated})` : ''}</summary>
              <table className="data-grid"><thead><tr><th>Скважина</th><th>Поле</th><th>Модель</th><th>Файл</th><th>Статус</th></tr></thead>
                <tbody>{cmp.rows.flatMap(r => Object.entries(r).filter(([k, v]) => k !== 'well' && typeof v === 'object' && (v as BaseModelCell).state !== 'same')
                  .map(([k, v]) => <tr key={r.well + k}><td>{r.well}</td><td>{k}</td><td>{num((v as BaseModelCell).model)}</td><td>{num((v as BaseModelCell).file)}</td>
                    <td>{STATE_TEXT[(v as BaseModelCell).state]}</td></tr>))}</tbody></table></details>
          )}
        </>
      )}
      {message && <div className="note">{message}</div>}
    </section>
  )
}


const STATUS_TEXT = { read: '✓ читается', found: '○ есть в модели, пока не читается', absent: '— не найдено' } as const
const size = (b: number) => (b > 1048576 ? (b / 1048576).toFixed(1) + ' МБ' : Math.max(1, Math.round(b / 1024)) + ' КБ')

/** Окно-чек-лист: какие файлы модели подключены (.data и INCLUDE) и что из найденного читается и куда попадает. */
function BaseModelChecklist({ data, onClose }: { data: BaseModelInventory | null; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="palette-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="menu-window" style={{ width: 'min(760px, calc(100vw - 32px))' }} role="dialog" aria-modal="true" aria-label="Что читается из базовой модели">
        <header className="menu-window-head">
          <h2>Что читается из базовой модели</h2>
          <button type="button" className="menu-close" onClick={onClose} aria-label="Закрыть" title="Закрыть (Esc)">×</button>
        </header>
        <div className="menu-groups">
          {!data && <p className="muted small">Просмотр файлов модели…</p>}
          {data?.error && <p className="warn">{data.error}</p>}
          {data && !data.error && <>
            <p className="muted small-text">Читается .data и всё, что подключено через INCLUDE (путь от папки самого .data). «Читается» — значение берётся и
              показывается в сверке; «есть в модели» — данные в файлах найдены, но программа их пока не использует.</p>
            <h3>Файлы ({data.files.length})</h3>
            <ul className="menu-items" style={{ marginLeft: 8 }}>
              {data.files.map((f, n) => <li key={n}>{f.found ? '✓' : '✗'} {f.parent ? '↳ ' : ''}<span title={f.path}>{f.name}</span>{' '}
                <small className="muted">{f.found ? size(f.size) + (f.big ? ', большой: просмотрены только отдельные слова' : '') : 'не найден'}{f.parent ? `, из ${f.parent}` : ''}</small></li>)}
            </ul>
            {data.groups.map(g => <section key={g.title}>
              <h3>{g.title}</h3>
              <table className="data-grid"><tbody>
                {g.items.map((it, n) => <tr key={n}>
                  <td style={{ whiteSpace: 'nowrap' }}>{STATUS_TEXT[it.status]}</td>
                  <td><b>{it.words.join(', ')}</b><br /><small className="muted">{it.what}{it.goes ? ' → ' + it.goes : ''}</small></td>
                  <td><small>{it.present.map(p => `${p.word} ×${p.count} (${p.files.join(', ')})`).join('; ')}</small></td></tr>)}
              </tbody></table></section>)}
            {data.other.length > 0 && <section><h3>Другие ключевые слова в файлах</h3>
              <p className="small">{data.other.map(o => `${o.word} ×${o.count}`).join(', ')}</p></section>}
            {data.notes.map((t, n) => <p key={n} className="muted small">{t}</p>)}
          </>}
        </div>
      </div>
    </div>
  )
}
