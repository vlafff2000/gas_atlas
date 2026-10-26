import { useEffect, useState } from 'react'
import { folderApi, FolderCheck, FolderEdit, FolderFile, FolderLoad, FolderLoadResult, FolderScan, ProjectFolders, RejectedMode } from './api_folder'
import { openFilePicker } from './FilePicker'
import { api, type Project } from './api'
import { importApi } from './api_import'

const KINDS = ['production', 'pressure', 'gdi', 'water'] as const

/** Папка, которую пользователь выбрал для проекта, — запоминаем в браузере (удобство, не данные проекта). */
const folderKey = (pid: string) => `atlas:folder:${pid}`
function rememberedFolder(pid: string): string {
  try { return localStorage.getItem(folderKey(pid)) ?? '' } catch { return '' }
}
function rememberFolder(pid: string, folder: string) {
  try { localStorage.setItem(folderKey(pid), folder) } catch { /* приватный режим: просто не запоминаем */ }
}
const KIND_LABEL: Record<string, string> = { production: 'Расходы', pressure: 'Давления', gdi: 'ГДИ', water: 'Вода' }
const LOAD_LABEL: Record<FolderLoad, string> = { loaded: 'загружен', changed: 'изменился, нужна загрузка', not_loaded: 'не загружен' }
/** Базовая модель участвует в общей проверке и загрузке как ещё один источник: подсказка, берутся только пропуски (файл главнее). */
const MODEL_FIELDS = ['x', 'y', 'perf']
const CHECK_LABEL: Record<FolderCheck['status'], string> = { ok: 'Готов к загрузке', attention: 'Есть замечания', error: 'Ошибка', skip: 'Тип не определён' }
const RESULT_LABEL: Record<FolderLoadResult['status'], string> = { loaded: 'Загружено', attention: 'Нужно внимание', error: 'Ошибка' }

/** Пробная проверка базовой модели проекта: сколько пропусков устья и перфорации она заполнит (расхождения с файлом не трогаются). */
async function checkModel(pid: string): Promise<FolderCheck | null> {
  const base = { name: 'Базовая модель', role: null, role_label: 'Базовая модель', issues: [], issues_count: 0 }
  try {
    const st = await importApi.baseModel(pid)
    if (!st.selected) return { ...base, status: 'skip', message: 'Модель не выбрана: выберите её в блоке «Базовая модель» выше, если нужны устье и перфорация из модели.' }
    if (st.error || st.error_model || !st.compare) return { ...base, status: 'error', message: st.error_model || st.error || 'Модель не прочитана' }
    const c = st.compare.counts
    const fill = MODEL_FIELDS.reduce((n, k) => n + (c[k]?.only_model ?? 0), 0)
    const diff = MODEL_FIELDS.reduce((n, k) => n + (c[k]?.diff ?? 0), 0)
    return { ...base, status: 'ok', message: `Скважин в модели: ${st.compare.wells}. Заполнит пропусков (устье X, Y, перфорация): ${fill}; расхождений с файлом: ${diff}, они не заменяются (файл главнее).` }
  } catch (e) {
    return { ...base, status: 'error', message: (e as Error).message }
  }
}

function kb(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

/** Раздел «Источники»: папка проекта, роли файлов, статус загрузки в проект и кнопка загрузки через общий импорт. */
export function FolderSources({ project, onProject }: { project: Project | null; onProject?: (p: Project) => void }) {
  const [folder, setFolder] = useState('')
  const [scan, setScan] = useState<FolderScan | null>(null)
  const [edits, setEdits] = useState<Record<string, FolderEdit>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [results, setResults] = useState<FolderLoadResult[]>([])
  const [warning, setWarning] = useState('')
  /** Снимок до последней загрузки пачкой: «Откатить загрузку из папки» возвращает данные к нему. */
  const [undo, setUndo] = useState('')
  /** Папка проекта, выбранная в «Базе ПХГ»: подпапки «готовые» и «выгрузки». */
  const [projectFolders, setProjectFolders] = useState<ProjectFolders | null>(null)

  /** Сводная проверка всех файлов с ролью (без записи в проект) и выбор, что грузить: решение за инженером, по умолчанию отмечено всё, что разобралось. */
  const [checks, setChecks] = useState<Record<string, FolderCheck>>({})
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [model, setModel] = useState<FolderCheck | null>(null)
  const [modelPicked, setModelPicked] = useState<boolean | null>(null)
  const [rejectedMode, setRejectedMode] = useState<RejectedMode>('skip')

  const run = async (work: () => Promise<FolderScan>, done: string) => {
    setBusy(true); setError(''); setMessage('')
    try {
      const next = await work()
      setScan(next); setFolder(next.folder); setEdits({}); setMessage(done); setResults([]); setWarning(''); setChecks({}); setPicked({}); setModel(null)
      if (project) rememberFolder(project.id, next.folder)
    } catch (e) {
      setScan(null); setEdits({})          // старый список не должен выглядеть как открытая папка
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // При открытии проекта тихо читаем его папку: сразу видно новые и изменённые файлы. Загрузка — только по кнопке.
  const pid = project?.id
  useEffect(() => {
    folderApi.projectState().then(setProjectFolders).catch(() => setProjectFolders(null))
  }, [])

  useEffect(() => {
    const saved = pid ? rememberedFolder(pid) : ''
    if (!pid || !saved) return
    folderApi.scan(saved, pid)
      .then(next => { setScan(next); setFolder(next.folder) })
      .catch(() => { /* папки уже нет или она недоступна: покажем обычную кнопку выбора */ })
  }, [pid])

  const pick = async () => {
    let chosen: string | null = null
    try {
      chosen = await openFilePicker({ mode: 'folder', start: folder || undefined, title: 'Папка проекта' })
    } catch (e) {
      setError((e as Error).message)
      return
    }
    if (chosen) await run(() => folderApi.scan(chosen!, project?.id), 'Папка прочитана.')
  }

  const current = (f: FolderFile) => ({
    role: f.role,
    normalized: f.normalized,
    ...edits[f.name],
  })

  const change = (f: FolderFile, patch: FolderEdit) => setEdits(prev => ({ ...prev, [f.name]: { ...prev[f.name], ...patch } }))

  const save = () => run(() => folderApi.saveManifest(scan!.folder, edits, project?.id), 'Роли сохранены в папке проекта.')

  // Грузим файлы с ролью, которые ещё не загружены или изменились; файлы без роли пропускаем.
  // Берём сохранённые роли: сервер при загрузке роли не читает. Несохранённые правки блокируют кнопку.
  const pending = scan?.files.filter(f => f.role && (f.load === 'not_loaded' || f.load === 'changed')).map(f => f.name) ?? []
  const unknownLoad = !!project && !!scan && scan.files.some(f => f.role && f.load === null)

  const undoLoad = async () => {
    if (!project || !undo) return
    setBusy(true); setError(''); setMessage('')
    try {
      const current = await api.project(project.id)
      onProject?.(await folderApi.undo(project.id, undo, current.revision))
      setUndo(''); setResults([])
      setScan(await folderApi.scan(scan!.folder, project.id))
      setMessage('Загрузка из папки отменена: данные проекта возвращены к состоянию до нее.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const loadPending = async () => {
    if (!project || !scan || dirty) return
    setBusy(true); setError(''); setMessage('')
    try {
      const reply = await folderApi.load(project.id, scan.folder, pending)
      setScan(reply.folder); setResults(reply.results); setWarning(reply.warning); setUndo(reply.undo ?? '')
      setMessage(`Загрузка выполнена: ${reply.results.filter(r => r.status === 'loaded').length} из ${reply.results.length}.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const checkable = scan?.files.filter(f => f.role).map(f => f.name) ?? []
  const isPicked = (name: string) => picked[name] ?? (checks[name] ? checks[name].status === 'ok' || checks[name].status === 'attention' : false)
  const chosen = Object.keys(checks).filter(isPicked)

  const checkAll = async () => {
    if (!project || !scan || dirty) return
    setBusy(true); setError(''); setMessage('')
    try {
      const reply = await folderApi.check(project.id, scan.folder, checkable)
      setChecks(Object.fromEntries(reply.results.map(r => [r.name, r]))); setPicked({}); setResults([])
      setModel(await checkModel(project.id)); setModelPicked(null)
      const bad = reply.results.filter(r => r.status === 'error' || r.status === 'skip').length
      setMessage(`Проверено файлов: ${reply.results.length}. В проект ничего не записано.` + (bad ? ` Не разобрано или без типа: ${bad}, остальные можно загружать.` : ''))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const modelOn = !!model && (modelPicked ?? model.status === 'ok')
  const total = chosen.length + (modelOn ? 1 : 0)

  const loadChosen = async () => {
    if (!project || !scan || dirty || !total) return
    setBusy(true); setError(''); setMessage('')
    try {
      const reply = chosen.length ? await folderApi.load(project.id, scan.folder, chosen, 'new', rejectedMode)
        : { folder: scan, results: [], warning: '', undo: '' }
      const out = [...reply.results]
      if (modelOn) {
        try {
          const r = await importApi.applyBaseModel(project.id, MODEL_FIELDS, 'fill')
          onProject?.(r.project)
          out.push({ name: 'Базовая модель', status: 'loaded', message: r.message })
        } catch (e) {
          out.push({ name: 'Базовая модель', status: 'error', message: (e as Error).message })
        }
      }
      setScan(reply.folder); setResults(out); setWarning(reply.warning); setUndo(reply.undo ?? '')
      setMessage(`Загрузка выполнена: ${out.filter(r => r.status === 'loaded').length} из ${out.length}.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const counts = (kind: string) => scan?.files.filter(f => current(f).role === kind).length ?? 0
  const dirty = Object.keys(edits).length > 0

  return (
    <section className="folder-sources" aria-label="Источники данных">
      <h2>Источники</h2>
      <p className="lede">Папка с файлами проекта: какой файл чем является. Укажите роли (многие определяются сами), нажмите «Проверить всё»: по каждому файлу будет сводка без записи в проект. Затем «Загрузить всё отмеченное». Роли и признак нормированной базы сохраняются в папке рядом с данными.</p>

      {project && projectFolders?.project && (
        <div className="folder-row" aria-label="Папка проекта из Базы ПХГ">
          <span className="muted">Папка проекта: {projectFolders.project}</span>
          {projectFolders.folders.map(f => (
            <button key={f.slot} type="button" disabled={busy || !f.found}
              onClick={() => run(() => folderApi.scan(f.path, project?.id), `Прочитана папка «${f.label}».`)}
              title={f.found ? `${f.files.length} файл(ов)` : 'Папки пока нет'}>
              Прочитать: {f.label} ({f.found ? f.files.length : 'нет'})
            </button>
          ))}
        </div>
      )}

      <div className="folder-row">
        <input
          type="text"
          value={folder}
          placeholder="Путь к папке"
          onChange={e => setFolder(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && folder.trim()) void run(() => folderApi.scan(folder.trim(), project?.id), 'Папка прочитана.') }}
        />
        <button type="button" onClick={pick} disabled={busy}>Выбрать папку</button>
        <button type="button" onClick={() => run(() => folderApi.scan(folder.trim(), project?.id), 'Папка прочитана.')} disabled={busy || !folder.trim()}>Показать файлы</button>
      </div>

      {error && <div className="note warning">{error}</div>}
      {scan?.warning && <div className="note">{scan.warning}</div>}
      {message && <div className="note">{message}</div>}

      {scan && scan.files.length > 0 && (
        <>
          <ul className="folder-checklist" aria-label="Что назначено по ролям">
            {KINDS.map(kind => (
              <li key={kind}>
                <strong>{KIND_LABEL[kind]}:</strong> {counts(kind) ? `${counts(kind)} файл(ов)` : 'нет файлов'}
              </li>
            ))}
          </ul>

          {project && (
            <div className="folder-row">
              <button type="button" onClick={loadPending} disabled={busy || dirty || pending.length === 0}>
                Загрузить новые и изменённые ({pending.length})
              </button>
              <span className="muted">Грузятся только файлы с ролью. Загрузка идёт через общий импорт проекта «{project.name}».</span>
              <button type="button" onClick={checkAll} disabled={busy || dirty || checkable.length === 0}
                title="Пробный разбор каждого файла по его роли: сколько строк, скважин, какой период и замечания. В проект ничего не пишется.">
                Проверить всё ({checkable.length})
              </button>
              {undo && <button type="button" className="quiet" onClick={undoLoad} disabled={busy}>Откатить загрузку из папки</button>}
            </div>
          )}
          {total > 0 || Object.keys(checks).length > 0 || model ? (
            <div className="folder-row">
              <button type="button" className="primary" onClick={loadChosen} disabled={busy || dirty || total === 0}>
                Загрузить всё отмеченное ({total})
              </button>
              <label className="muted">Файл с отклонёнными строками:{' '}
                <select value={rejectedMode} onChange={e => setRejectedMode(e.target.value as RejectedMode)}>
                  <option value="skip">не загружать, разобрать вручную</option>
                  <option value="accept">загрузить только корректные строки</option>
                  <option value="keep">загрузить все, плохие исключить из расчётов</option>
                </select></label>
              <span className="muted">Отметки в колонке «Загрузить» можно менять: ошибка в одном файле остальные не блокирует.</span>
            </div>
          ) : null}
          {model && (
            <div className="note" aria-label="Базовая модель в общей загрузке">
              <label><input type="checkbox" checked={modelOn} disabled={model.status === 'skip' || model.status === 'error'}
                onChange={e => setModelPicked(e.target.checked)} /> <strong>Базовая модель: {CHECK_LABEL[model.status]}</strong></label>
              <div>{model.message}</div>
            </div>
          )}
          {!project && <div className="note">Выберите проект, чтобы видеть, что загружено, и загружать файлы.</div>}
          {unknownLoad && <div className="note">Статус загрузки не показан для выбранного проекта: нажмите «Показать файлы» ещё раз.</div>}
          {dirty && <div className="note">Сначала сохраните роли: загрузка идёт по сохранённым ролям.</div>}
          {warning && <div className="note warning">{warning}</div>}
          {results.length > 0 && (
            <ul className="folder-results">
              {results.map(r => (
                <li key={r.name}><strong>{r.name}:</strong> {RESULT_LABEL[r.status]}. {r.message}</li>
              ))}
            </ul>
          )}

          <table className="folder-table">
            <thead>
              <tr><th>Файл</th><th>Размер</th><th>Роль</th><th>Нормирована</th><th>Загрузка</th><th>Проверка перед загрузкой</th><th>Результат Базы ПХГ и проверка</th></tr>
            </thead>
            <tbody>
              {scan.files.map(f => {
                const cur = current(f)
                return (
                  <tr key={f.name}>
                    <td>{f.name}<div className="muted">{f.modified}</div></td>
                    <td>{kb(f.size)}</td>
                    <td>
                      <select value={cur.role ?? ''} onChange={e => change(f, { role: e.target.value || null })} aria-label={`Роль файла ${f.name}`}>
                        <option value="">не назначено</option>
                        {scan.roles.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </select>
                      {!edits[f.name]?.role && (f.role_reason
                        ? <div className="muted" title={f.role_reason}>{f.role_source === 'manifest' ? f.role_reason : `${f.role_source === 'content' || !f.role ? 'по содержимому' : 'по имени'}: ${f.role_reason.replace(/^(По имени файла|Содержимое): /, '')}`}</div>
                        : !f.known && <div className="muted">тип не определён ни по имени, ни по содержимому: выберите роль</div>)}
                    </td>
                    <td>
                      {cur.role === 'production'
                        ? <input type="checkbox" checked={cur.normalized} onChange={e => change(f, { normalized: e.target.checked })} aria-label={`Нормирована ${f.name}`} />
                        : <span className="muted">—</span>}
                    </td>
                    <td>
                      {f.load ? LOAD_LABEL[f.load] : <span className="muted">—</span>}
                    </td>
                    <td>
                      {checks[f.name] ? (
                        <>
                          <label><input type="checkbox" checked={isPicked(f.name)} onChange={e => setPicked(prev => ({ ...prev, [f.name]: e.target.checked }))}
                            aria-label={`Загрузить ${f.name}`} /> <strong>{CHECK_LABEL[checks[f.name].status]}</strong></label>
                          <div>{checks[f.name].message}</div>
                          {checks[f.name].issues.length > 0 && (
                            <details><summary className="muted">Замечания: {checks[f.name].issues_count}</summary>
                              <ul>{checks[f.name].issues.map((x, i) => <li key={i} className="small">{x.level ? `${x.level}: ` : ''}{x.reason}</li>)}</ul></details>)}
                        </>
                      ) : <span className="muted">не проверялся</span>}
                    </td>
                    <td>
                      {f.known && <div>{f.known}</div>}
                      {f.qc && (f.qc.error
                        ? <div className="muted">{f.qc.error}</div>
                        : <div>Проверка{f.qc.summary ? `: ${f.qc.summary}` : ''} <span className="muted">({f.qc.file})</span></div>)}
                      {!f.known && !f.qc && <span className="muted">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          <details>
            <summary className="muted">Что Атлас узнаёт из выходных файлов Базы ПХГ ({scan.registry.length})</summary>
            <table className="folder-table">
              <thead><tr><th>Признак</th><th>Что это</th><th>Роль при загрузке</th></tr></thead>
              <tbody>
                {scan.registry.map((r, i) => (
                  <tr key={i}>
                    <td>{r.by === 'name' ? `имя начинается с «${r.match}»` : r.match}</td>
                    <td>{r.label}</td>
                    <td>{r.role ? scan.roles.find(x => x.value === r.role)?.label ?? r.role : 'не грузится'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          <div className="folder-row">
            <button type="button" onClick={save} disabled={busy || !dirty}>Сохранить роли</button>
            {dirty && <span className="muted">Есть несохранённые изменения</span>}
          </div>
        </>
      )}
    </section>
  )
}
